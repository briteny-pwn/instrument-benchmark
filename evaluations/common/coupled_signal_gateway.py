"""Raw-protocol gateway for a causally coupled source/DUT/measurement bench."""

from __future__ import annotations

import base64
import json
import re
import socketserver
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import raw_trace


DEFAULT_RESET_STATE: dict[str, dict[str, Any]] = {
    "psu": {"voltage": 0.0, "current_limit": 0.0, "output": False},
    "switch": {"closed_paths": []},
    "awg": {
        "waveforms": {},
        "selected_waveform": "NONE",
        "amplitude": 1.0,
        "offset": 0.0,
        "frequency": 1000.0,
        "output": False,
    },
    "scope": {
        "source": "CH2",
        "encoding": "ASCII",
        "width": 2,
        "ymult": 1.0,
        "yoff": 0.0,
        "yzero": 0.0,
    },
    "dmm": {"mode": "NONE", "range": 1.0, "sample_count": 1, "trigger_source": "BUS"},
}


class Gateway:
    """Expose independent resources whose observations share one hidden signal model."""

    def __init__(self, scenario_path: Path) -> None:
        self.scenario_path = scenario_path.resolve()
        self.scenario = json.loads(self.scenario_path.read_text(encoding="utf-8"))
        resources = self.scenario.get("resources", [])
        self.resource_defs = {str(item["name"]): item for item in resources}
        self.role_resources = {str(item["role"]): str(item["name"]) for item in resources}
        self.reset_state = deepcopy(DEFAULT_RESET_STATE)
        _deep_update(self.reset_state, self.scenario.get("reset_state", {}))
        self.state = deepcopy(self.reset_state)
        _deep_update(self.state, self.scenario.get("initial_state", {}))
        self.physics = self.scenario.get("physics", {})
        self.handles: dict[str, str] = {}
        self.handle_counter = 0
        self.last_observations: dict[str, Any] = {}
        self.server: socketserver.ThreadingTCPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self, host: str = "127.0.0.1", port: int = 0) -> tuple[str, int]:
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

        self.server = Server((host, port), Handler)
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
            "last_observations": deepcopy(self.last_observations),
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
            trace_response = response.decode("latin-1") if isinstance(response, bytes) else str(response)
            raw_trace.record(
                "query_raw" if op == "query_raw" else "query",
                {"handle": handle, "command": command, "response": trace_response},
            )
            if isinstance(response, bytes) or op == "query_raw":
                data = response if isinstance(response, bytes) else str(response).encode("latin-1")
                return {"ok": True, "encoding": "base64", "data": base64.b64encode(data).decode("ascii")}
            return {"ok": True, "response": str(response)}
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
            self.state[role] = deepcopy(self.reset_state[role])
            return
        if role == "psu":
            if match := re.fullmatch(r":SOUR:VOLT\s+([-+0-9.E]+)", normalized):
                self.state[role]["voltage"] = float(match.group(1))
                return
            if match := re.fullmatch(r":SOUR:CURR\s+([-+0-9.E]+)", normalized):
                self.state[role]["current_limit"] = float(match.group(1))
                return
            if match := re.fullmatch(r":OUTP\s+(ON|OFF)", normalized):
                self.state[role]["output"] = match.group(1) == "ON"
                return
        elif role == "switch":
            if normalized == "ROUT:OPEN:ALL":
                self.state[role]["closed_paths"] = []
                return
            if match := re.fullmatch(r"ROUT:CLOS\s+\(@([0-9, ]+)\)", normalized):
                self.state[role]["closed_paths"] = [int(item) for item in match.group(1).split(",")]
                return
        elif role == "awg":
            if normalized.startswith("DATA:ARB "):
                fields = command.strip()[len("DATA:ARB ") :].split(",")
                if len(fields) < 2:
                    raise RuntimeError("Waveform upload requires a name and numeric points")
                self.state[role]["waveforms"][fields[0].strip().upper()] = [
                    float(item.strip()) for item in fields[1:]
                ]
                return
            if match := re.fullmatch(r"FUNC:ARB\s+(\S+)", normalized):
                self.state[role]["selected_waveform"] = match.group(1)
                return
            if match := re.fullmatch(r"VOLT:OFFS\s+([-+0-9.E]+)", normalized):
                self.state[role]["offset"] = float(match.group(1))
                return
            if match := re.fullmatch(r"VOLT\s+([-+0-9.E]+)", normalized):
                self.state[role]["amplitude"] = float(match.group(1))
                return
            if match := re.fullmatch(r"FREQ\s+([-+0-9.E]+)", normalized):
                self.state[role]["frequency"] = float(match.group(1))
                return
            if match := re.fullmatch(r"OUTP\s+(ON|OFF)", normalized):
                self.state[role]["output"] = match.group(1) == "ON"
                return
        elif role == "scope":
            setters = (
                (r"DATA:SOURCE\s+(\S+)", "source", str),
                (r"DATA:ENCODING\s+(\S+)", "encoding", str),
                (r"DATA:WIDTH\s+(\d+)", "width", int),
                (r"WFMOUTPRE:YMULT\s+([-+0-9.E]+)", "ymult", float),
                (r"WFMOUTPRE:YOFF\s+([-+0-9.E]+)", "yoff", float),
                (r"WFMOUTPRE:YZERO\s+([-+0-9.E]+)", "yzero", float),
            )
            for pattern, key, parser in setters:
                if match := re.fullmatch(pattern, normalized):
                    self.state[role][key] = parser(match.group(1))
                    return
        elif role == "dmm":
            if normalized == "CONF:VOLT:DC":
                self.state[role]["mode"] = "VOLT:DC"
                return
            setters = (
                (r"VOLT:RANG\s+([-+0-9.E]+)", "range", float),
                (r"SAMP:COUN\s+(\d+)", "sample_count", int),
                (r"TRIG:SOUR\s+(\S+)", "trigger_source", str),
            )
            for pattern, key, parser in setters:
                if match := re.fullmatch(pattern, normalized):
                    self.state[role][key] = parser(match.group(1))
                    return
            if normalized == "INIT":
                self.state[role]["initiated"] = True
                return
        raise RuntimeError(f"Unsupported write command for {role}: {command}")

    def _query(self, role: str, command: str) -> str | bytes:
        normalized = _normalize(command)
        if normalized == "*IDN?":
            resource = self.role_resources[role]
            return str(self.resource_defs[resource]["idn"])
        if role == "psu":
            if normalized == ":OUTP?":
                return "1" if self.state[role]["output"] else "0"
            if normalized == ":MEAS:VOLT?":
                value = self._supply_voltage()
                self.last_observations["supply_voltage_v"] = value
                return f"{value:.6f}"
        elif role == "switch" and normalized == "ROUT:CLOS?":
            paths = self.state[role]["closed_paths"]
            return "(@" + ",".join(str(item) for item in paths) + ")" if paths else "(@)"
        elif role == "awg" and normalized == "OUTP?":
            return "1" if self.state[role]["output"] else "0"
        elif role == "dmm" and normalized == "FETCH:VOLT?":
            values = self._dmm_values()
            self.last_observations["dmm_samples_v"] = values
            return ",".join(f"{value:.6f}" for value in values)
        elif role == "scope" and normalized == "CURVE?":
            block, raw_codes, voltages = self._scope_block()
            self.last_observations["scope_raw_codes"] = raw_codes
            self.last_observations["scope_voltages_v"] = voltages
            return block
        raise RuntimeError(f"Unsupported query command for {role}: {command}")

    def _supply_voltage(self) -> float:
        if not self.state["psu"]["output"]:
            return 0.0
        return (
            float(self.state["psu"]["voltage"]) * float(self.physics.get("supply_gain", 1.0))
            + float(self.physics.get("supply_offset_v", 0.0))
        )

    def _dut_signal(self) -> list[float]:
        awg = self.state["awg"]
        points = list(awg["waveforms"].get(awg["selected_waveform"], []))
        fallback_count = int(self.state["dmm"].get("sample_count", 8))
        if not points:
            points = [0.0] * max(1, fallback_count)
        required_paths = set(int(item) for item in self.physics.get("required_paths", [101, 102]))
        active = (
            self.state["psu"]["output"]
            and self.state["awg"]["output"]
            and required_paths.issubset(set(self.state["switch"]["closed_paths"]))
        )
        if not active:
            return [0.0] * len(points)
        nominal_supply = float(self.physics.get("nominal_supply_v", 5.0))
        nominal_amplitude = float(self.physics.get("nominal_awg_amplitude_v", 1.2))
        supply_factor = self._supply_voltage() / nominal_supply if nominal_supply else 0.0
        amplitude_factor = float(awg["amplitude"]) / nominal_amplitude if nominal_amplitude else 0.0
        gain = float(self.physics.get("dut_gain", 1.0))
        offset = float(self.physics.get("dut_offset_v", 0.0))
        return [
            ((point * amplitude_factor) + float(awg["offset"])) * gain * supply_factor + offset
            for point in points
        ]

    def _dmm_values(self) -> list[float]:
        count = max(1, int(self.state["dmm"].get("sample_count", 1)))
        signal = _resize(self._dut_signal(), count)
        noise = _resize([float(value) for value in self.physics.get("dmm_noise_v", [0.0])], count)
        bias = float(self.physics.get("dmm_bias_v", 0.0))
        return [value + bias + perturbation for value, perturbation in zip(signal, noise)]

    def _scope_block(self) -> tuple[bytes, list[int], list[float]]:
        signal = self._dut_signal()
        noise = _resize([float(value) for value in self.physics.get("scope_noise_v", [0.0])], len(signal))
        scope = self.state["scope"]
        ymult = float(scope["ymult"])
        if ymult == 0:
            raise RuntimeError("Scope YMULT must be non-zero")
        yoff = float(scope["yoff"])
        yzero = float(scope["yzero"])
        raw_codes = [
            max(0, min(255, round(((value + perturbation) - yzero) / ymult + yoff)))
            for value, perturbation in zip(signal, noise)
        ]
        voltages = [(code - yoff) * ymult + yzero for code in raw_codes]
        payload = bytes(raw_codes)
        length = str(len(payload)).encode("ascii")
        block = b"#" + str(len(length)).encode("ascii") + length + payload
        return block, raw_codes, voltages


def _normalize(command: str) -> str:
    return " ".join(str(command).strip().upper().split())


def _resize(values: list[float], count: int) -> list[float]:
    if not values:
        return [0.0] * count
    return [values[index % len(values)] for index in range(count)]


def _deep_update(target: dict[str, Any], override: dict[str, Any]) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = deepcopy(value)
