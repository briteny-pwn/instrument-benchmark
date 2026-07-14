"""JSON-line socket gateway backed by hidden yaqd-fakes daemons."""

from __future__ import annotations

import json
import math
import os
import shutil
import socket
import socketserver
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import tomli_w
import yaqc

from . import raw_trace


SCRIPT_BY_KIND = {
    "fake-sensor": "yaqd-fake-sensor",
    "fake-continuous-hardware": "yaqd-fake-continuous-hardware",
    "fake-spectrometer": "yaqd-fake-spectrometer",
}


class Gateway:
    def __init__(self, scenario_path: Path) -> None:
        self.scenario_path = scenario_path.resolve()
        self.scenario = json.loads(self.scenario_path.read_text(encoding="utf-8"))
        self.resource_defs = {item["name"]: item for item in self.scenario.get("resources", [])}
        self.tempdir: tempfile.TemporaryDirectory[str] | None = None
        self.processes: dict[str, subprocess.Popen[str]] = {}
        self.clients: dict[str, Any] = {}
        self.resources: dict[str, dict[str, Any]] = {}
        self.handle_counter = 0
        self.server: socketserver.ThreadingTCPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> tuple[str, int]:
        self.tempdir = tempfile.TemporaryDirectory(prefix="instrument-benchmark-yaq-")
        self._start_daemons()
        gateway = self

        class Handler(socketserver.StreamRequestHandler):
            def setup(self) -> None:
                super().setup()
                raw_trace.record("socket_connect", {"client": repr(self.client_address)})

            def handle(self) -> None:
                for line in self.rfile:
                    try:
                        request = json.loads(line.decode("utf-8"))
                        response = gateway.dispatch(request)
                    except Exception as exc:  # pragma: no cover - defensive boundary
                        response = {"ok": False, "error": str(exc)}
                    self.wfile.write((json.dumps(response) + "\n").encode("utf-8"))
                    self.wfile.flush()

            def finish(self) -> None:
                raw_trace.record("socket_disconnect", {"client": repr(self.client_address)})
                super().finish()

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server(("127.0.0.1", 0), Handler)
        host, port = self.server.server_address
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        raw_trace.record("gateway_start", {"host": host, "port": port, "backend": str(self.scenario_path)})
        return str(host), int(port)

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        for client in list(self.clients.values()):
            try:
                client.shutdown(False)
            except Exception:
                pass
            try:
                client._socket._socket.close()
            except Exception:
                pass
        for process in list(self.processes.values()):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
        self.resources.clear()
        self.clients.clear()
        self.processes.clear()
        if self.tempdir is not None:
            self.tempdir.cleanup()
        raw_trace.record("gateway_stop", {})

    def snapshot_state(self) -> dict[str, Any]:
        resources: dict[str, Any] = {}
        for resource_name, client in self.clients.items():
            entry: dict[str, Any] = {}
            try:
                entry["id"] = client.id()
            except Exception as exc:
                entry["id_error"] = str(exc)
            try:
                entry["busy"] = client.busy()
            except Exception:
                pass
            for method_name in ("get_position", "get_destination", "get_central_wavelength"):
                if hasattr(client, method_name):
                    try:
                        entry[method_name[4:]] = getattr(client, method_name)()
                    except Exception as exc:
                        entry[f"{method_name}_error"] = str(exc)
            resources[resource_name] = entry
        return {
            "resources": resources,
            "open_handles": sorted(self.resources),
        }

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        op = request.get("op")
        raw_trace.record("request", request)
        if op == "list_resources":
            resources = list(self.resource_defs)
            raw_trace.record("list_resources", {"resources": resources})
            return {"ok": True, "resources": resources}
        if op == "open":
            resource_name = str(request["resource"])
            if resource_name not in self.resource_defs:
                return {"ok": False, "error": f"Unknown resource: {resource_name}"}
            self.handle_counter += 1
            handle = f"h{self.handle_counter}"
            self.resources[handle] = {"name": resource_name, "definition": self.resource_defs[resource_name]}
            raw_trace.record(
                "open",
                {
                    "handle": handle,
                    "resource": resource_name,
                    "timeout": int(request.get("timeout", 10000)),
                    "read_termination": request.get("read_termination", "\n"),
                    "write_termination": request.get("write_termination", "\n"),
                    "timeout_explicit": "timeout" in request,
                    "read_termination_explicit": "read_termination" in request,
                    "write_termination_explicit": "write_termination" in request,
                },
            )
            return {"ok": True, "handle": handle}
        if op == "write":
            handle = str(request["handle"])
            command = str(request["command"])
            self._dispatch_command(handle, "write", command)
            raw_trace.record("write", {"handle": handle, "command": command})
            return {"ok": True}
        if op == "query":
            handle = str(request["handle"])
            command = str(request["command"])
            response = self._dispatch_command(handle, "query", command)
            raw_trace.record("query", {"handle": handle, "command": command, "response": response})
            return {"ok": True, "response": str(response)}
        if op == "close":
            handle = str(request["handle"])
            self.resources.pop(handle, None)
            raw_trace.record("close", {"handle": handle})
            return {"ok": True}
        return {"ok": False, "error": f"Unsupported operation: {op!r}"}

    def _start_daemons(self) -> None:
        assert self.tempdir is not None
        base = Path(self.tempdir.name)
        for resource_name, definition in self.resource_defs.items():
            kind = definition["kind"]
            if kind not in SCRIPT_BY_KIND:
                raise RuntimeError(f"Unsupported yaq fake kind: {kind}")
            port = _find_free_port()
            config = dict(definition.get("config", {}))
            config.update({"host": "127.0.0.1", "port": port, "log_level": "error", "log_to_file": False})
            daemon_name = definition.get("daemon_name", resource_name.replace("::", "_").lower())
            config_path = base / f"{daemon_name}.toml"
            config_path.write_text(tomli_w.dumps({daemon_name: config}), encoding="utf-8")
            env = os.environ.copy()
            env["HOME"] = str(base)
            repo_script = Path(__file__).resolve().parents[2] / ".venv" / "bin" / SCRIPT_BY_KIND[kind]
            script = str(repo_script) if repo_script.exists() else shutil.which(SCRIPT_BY_KIND[kind])
            if script is None:
                raise RuntimeError(f"Could not find yaqd-fakes console script: {SCRIPT_BY_KIND[kind]}")
            process = subprocess.Popen(
                [script, "--config", str(config_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            client = self._wait_for_client(process, port, resource_name)
            self.processes[resource_name] = process
            self.clients[resource_name] = client
            raw_trace.record("yaq_daemon_start", {"resource": resource_name, "kind": kind, "port": port})

    def _wait_for_client(self, process: subprocess.Popen[str], port: int, resource_name: str) -> Any:
        deadline = time.time() + 8
        last_error: Exception | None = None
        while time.time() < deadline:
            if process.poll() is not None:
                stdout = process.stdout.read() if process.stdout else ""
                stderr = process.stderr.read() if process.stderr else ""
                raise RuntimeError(f"yaqd-fakes daemon for {resource_name} exited early: {stdout}{stderr}")
            try:
                return yaqc.Client(port, host="127.0.0.1", timeout=10)
            except Exception as exc:
                last_error = exc
                time.sleep(0.1)
        raise RuntimeError(f"Timed out connecting to yaqd-fakes daemon for {resource_name}: {last_error}")

    def _dispatch_command(self, handle: str, kind: str, command: str) -> Any:
        if handle not in self.resources:
            raise RuntimeError(f"Unknown handle: {handle}")
        entry = self.resources[handle]
        definition = entry["definition"]
        client = self.clients[entry["name"]]
        tokens = command.strip().split()
        normalized = " ".join(tokens).upper()
        if not tokens:
            raise RuntimeError("Empty command")
        if normalized == "*IDN?":
            ident = client.id()
            return f"YAQ,{ident.get('kind')},{ident.get('name')},{ident.get('serial')}"
        if normalized == "STATE?":
            return _one_line(client.get_state())
        if normalized == "BUSY?":
            return "TRUE" if client.busy() else "FALSE"
        if definition["kind"] == "fake-sensor":
            return _dispatch_sensor(client, kind, tokens, normalized)
        if definition["kind"] == "fake-continuous-hardware":
            return _dispatch_positioner(client, kind, tokens, normalized)
        if definition["kind"] == "fake-spectrometer":
            return _dispatch_spectrometer(client, kind, tokens, normalized)
        raise RuntimeError(f"Unsupported yaq fake kind: {definition['kind']}")


def _dispatch_sensor(client: Any, kind: str, tokens: list[str], normalized: str) -> str:
    if kind != "query":
        raise RuntimeError("Sensor supports query commands only")
    if normalized == "CHANNELS?":
        return ",".join(client.get_channel_names())
    if len(tokens) == 2 and tokens[0].upper() == "MEASURE?":
        channel = tokens[1]
        measured = client.get_measured()
        if channel not in measured:
            raise RuntimeError(f"Unknown channel: {channel}")
        return f"MEASURED {channel} {_format_number(measured[channel])} ID {measured.get('measurement_id')}"
    raise RuntimeError(f"Unsupported sensor command: {' '.join(tokens)}")


def _dispatch_positioner(client: Any, kind: str, tokens: list[str], normalized: str) -> str:
    if kind == "write" and len(tokens) == 2 and tokens[0].upper() == "SET_POSITION":
        client.set_position(float(tokens[1]))
        return "OK"
    if kind != "query":
        raise RuntimeError("Positioner write command must be SET_POSITION <value>")
    if normalized == "POSITION?":
        return f"POSITION {_format_number(client.get_position())}"
    if normalized == "DESTINATION?":
        return f"DESTINATION {_format_number(client.get_destination())}"
    if normalized == "LIMITS?":
        limits = client.get_limits()
        return f"LIMITS {_format_number(limits[0])},{_format_number(limits[1])}"
    if normalized == "UNITS?":
        return f"UNITS {client.get_units()}"
    raise RuntimeError(f"Unsupported positioner command: {' '.join(tokens)}")


def _dispatch_spectrometer(client: Any, kind: str, tokens: list[str], normalized: str) -> str:
    if kind == "write" and len(tokens) == 2 and tokens[0].upper() == "SET_CENTER":
        client.set_central_wavelength(float(tokens[1]))
        return "OK"
    if kind != "query":
        raise RuntimeError("Spectrometer write command must be SET_CENTER <nm>")
    if normalized == "CENTER?":
        return f"CENTER {_format_number(client.get_central_wavelength())}"
    if normalized == "MEASURE":
        return f"MEASUREMENT_ID {client.measure(False)}"
    if normalized == "WAVELENGTHS?":
        mappings = client.get_mappings()
        return "WAVELENGTHS " + ",".join(_format_number(v) for v in _to_list(mappings["wavelengths"]))
    if normalized == "COUNTS?":
        measured = client.get_measured()
        return "COUNTS " + ",".join(_format_number(v) for v in _to_list(measured["counts"]))
    raise RuntimeError(f"Unsupported spectrometer command: {' '.join(tokens)}")


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _one_line(value: Any) -> str:
    return " ".join(str(value).strip().split())


def _to_list(value: Any) -> list[Any]:
    if hasattr(value, "tolist"):
        return list(value.tolist())
    return list(value)


def _format_number(value: Any) -> str:
    numeric = float(value)
    if math.isclose(numeric, round(numeric), abs_tol=1e-12):
        return str(int(round(numeric)))
    return f"{numeric:.12g}"
