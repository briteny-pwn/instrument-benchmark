"""Raw-protocol gateway for causally coupled source/measurement sweeps."""

from __future__ import annotations

import json
import re
import socketserver
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import raw_trace


class Gateway:
    def __init__(self, scenario_path: Path) -> None:
        self.scenario_path = scenario_path.resolve()
        self.scenario = json.loads(self.scenario_path.read_text(encoding="utf-8"))
        self.resource_defs = {str(item["name"]): item for item in self.scenario["resources"]}
        self.role_resources = {str(item["role"]): str(item["name"]) for item in self.scenario["resources"]}
        self.reset_state = {
            "source": {"setpoint_v": 0.0, "output": False},
            "dmm": {"mode": "NONE"},
        }
        self.state = deepcopy(self.reset_state)
        for role, values in self.scenario.get("initial_state", {}).items():
            self.state.setdefault(role, {}).update(deepcopy(values))
        self.physics = self.scenario.get("physics", {})
        self.handles: dict[str, str] = {}
        self.handle_counter = 0
        self.measurement_index = 0
        self.observations: list[dict[str, float]] = []
        self.server: socketserver.ThreadingTCPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> tuple[str, int]:
        gateway = self

        class Handler(socketserver.StreamRequestHandler):
            def setup(self) -> None:
                super().setup()
                raw_trace.record("socket_connect", {"client": repr(self.client_address)})

            def handle(self) -> None:
                for line in self.rfile:
                    try:
                        response = gateway.dispatch(json.loads(line.decode("utf-8")))
                    except Exception as exc:  # pragma: no cover - socket boundary
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
        self.handles.clear()
        raw_trace.record("gateway_stop", {})

    def snapshot_state(self) -> dict[str, Any]:
        return {
            "backend": str(self.scenario_path),
            "resources": list(self.resource_defs),
            "open_handles": sorted(self.handles),
            "instrument_state": deepcopy(self.state),
            "observations": deepcopy(self.observations),
        }

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        op = request.get("op")
        raw_trace.record("request", request)
        if op == "list_resources":
            resources = list(self.resource_defs)
            raw_trace.record("list_resources", {"resources": resources})
            return {"ok": True, "resources": resources}
        if op == "open":
            resource = str(request["resource"])
            if resource not in self.resource_defs:
                raise RuntimeError(f"Unknown resource: {resource}")
            self.handle_counter += 1
            handle = f"h{self.handle_counter}"
            self.handles[handle] = resource
            raw_trace.record(
                "open",
                {
                    "handle": handle,
                    "resource": resource,
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
            self._write(self._role(handle), command)
            raw_trace.record("write", {"handle": handle, "command": command})
            return {"ok": True}
        if op in {"query", "query_raw"}:
            handle = str(request["handle"])
            command = str(request["command"])
            response = self._query(self._role(handle), command)
            raw_trace.record("query", {"handle": handle, "command": command, "response": response})
            return {"ok": True, "response": response}
        if op == "close":
            handle = str(request["handle"])
            self.handles.pop(handle, None)
            raw_trace.record("close", {"handle": handle})
            return {"ok": True}
        return {"ok": False, "error": f"Unsupported operation: {op!r}"}

    def _role(self, handle: str) -> str:
        resource = self.handles.get(handle)
        if resource is None:
            raise RuntimeError(f"Unknown handle: {handle}")
        return str(self.resource_defs[resource]["role"])

    def _write(self, role: str, command: str) -> None:
        normalized = _normalize(command)
        if normalized == "*RST":
            if role in self.reset_state:
                self.state[role] = deepcopy(self.reset_state[role])
            return
        if role == "source":
            if match := re.fullmatch(r"OUTP\s+(ON|OFF)", normalized):
                self.state[role]["output"] = match.group(1) == "ON"
                return
            if match := re.fullmatch(r"SOUR:GATE\s+([-+0-9.E]+)", normalized):
                self.state[role]["setpoint_v"] = float(match.group(1))
                return
        if role == "dmm" and normalized == "CONF:VOLT:DC":
            self.state[role]["mode"] = "VOLT:DC"
            return
        raise RuntimeError(f"Unsupported write command for {role}: {command}")

    def _query(self, role: str, command: str) -> str:
        normalized = _normalize(command)
        if normalized == "*IDN?":
            return str(self.resource_defs[self.role_resources[role]]["idn"])
        if role == "source" and normalized == "OUTP?":
            return "1" if self.state[role]["output"] else "0"
        if role == "dmm" and re.fullmatch(r"READ:VOLT\?\s+[-+0-9.E]+", normalized):
            requested = float(normalized.split()[-1])
            actual = float(self.state["source"]["setpoint_v"])
            value = self._measure(actual)
            self.observations.append(
                {"requested_setpoint_v": requested, "actual_setpoint_v": actual, "measured_voltage_v": value}
            )
            return f"{value:.9f}"
        raise RuntimeError(f"Unsupported query command for {role}: {command}")

    def _measure(self, setpoint: float) -> float:
        if not self.state["source"]["output"]:
            return float(self.physics.get("output_off_reading_v", 0.0))
        noise = [float(item) for item in self.physics.get("noise_v", [0.0])]
        perturbation = noise[self.measurement_index % len(noise)] if noise else 0.0
        self.measurement_index += 1
        return (
            float(self.physics.get("slope", 1.0)) * setpoint
            + float(self.physics.get("intercept_v", 0.0))
            + float(self.physics.get("quadratic", 0.0)) * setpoint * setpoint
            + perturbation
        )


def _normalize(command: str) -> str:
    return " ".join(str(command).strip().upper().split())
