"""Trace wrapper for running resource discovery candidates against pyvisa-sim."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyvisa


RESOURCE_NAME = "TCPIP0::198.51.100.30::inst0::INSTR"
SIM_YAML = Path(__file__).resolve().parent / "pyvisa_sim" / "mocklogger300.yaml"

TRACE: list["TraceEvent"] = []


@dataclass
class TraceEvent:
    kind: str
    payload: dict[str, Any]


def install() -> None:
    if getattr(pyvisa.ResourceManager, "_instrument_benchmark_traced", False):
        return

    original_resource_manager = pyvisa.ResourceManager

    class TracedResourceManager:
        _instrument_benchmark_traced = True

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            backend_args = args or (f"{SIM_YAML}@sim",)
            self._rm = original_resource_manager(*backend_args, **kwargs)
            TRACE.append(TraceEvent("resource_manager", {"backend": str(backend_args[0])}))

        def list_resources(self, *args: Any, **kwargs: Any) -> tuple[str, ...]:
            resources = self._rm.list_resources(*args, **kwargs)
            TRACE.append(TraceEvent("list_resources", {"resources": list(resources), "args": list(args), "kwargs": dict(kwargs)}))
            return resources

        def open_resource(self, resource_name: str, *args: Any, **kwargs: Any) -> "TracedResource":
            TRACE.append(TraceEvent("open_resource", {"resource_name": resource_name}))
            resource = self._rm.open_resource(resource_name, *args, **kwargs)
            return TracedResource(resource, resource_name)

        def close(self) -> None:
            TRACE.append(TraceEvent("close_resource_manager", {}))
            self._rm.close()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._rm, name)

    pyvisa.ResourceManager = TracedResourceManager  # type: ignore[assignment]


class TracedResource:
    def __init__(self, resource: Any, resource_name: str) -> None:
        object.__setattr__(self, "_resource", resource)
        object.__setattr__(self, "_resource_name", resource_name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"timeout", "read_termination", "write_termination"}:
            TRACE.append(TraceEvent("set_attribute", {"resource_name": self._resource_name, "name": name, "value": value}))
        setattr(self._resource, name, value)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resource, name)

    def write(self, command: str, *args: Any, **kwargs: Any) -> Any:
        TRACE.append(TraceEvent("write", {"resource_name": self._resource_name, "command": command}))
        result = self._resource.write(command, *args, **kwargs)
        _record_semantic(self._resource_name, command, is_query=False)
        return result

    def query(self, command: str, *args: Any, **kwargs: Any) -> Any:
        TRACE.append(TraceEvent("query", {"resource_name": self._resource_name, "command": command}))
        result = self._resource.query(command, *args, **kwargs)
        _record_semantic(self._resource_name, command, is_query=True)
        return result

    def close(self) -> None:
        TRACE.append(TraceEvent("close_resource", {"resource_name": self._resource_name}))
        self._resource.close()


def reset_trace() -> None:
    TRACE.clear()


def _record_semantic(resource_name: str, command: str, is_query: bool) -> None:
    normalized = _normalize(command)
    payload: dict[str, Any] = {"resource_name": resource_name}
    if normalized == "*IDN?":
        payload["action"] = "identify"
    elif normalized == "*RST" and not is_query:
        payload["action"] = "reset"
    elif normalized == "SENS:CHAN A" and not is_query:
        payload.update({"action": "select_channel", "channel": "A"})
    elif normalized == "MEAS:TEMP? A" and is_query:
        payload.update({"action": "measure_temperature", "channel": "A"})
    elif normalized == "MEAS:HUM? A" and is_query:
        payload.update({"action": "measure_humidity", "channel": "A"})
    else:
        return
    TRACE.append(TraceEvent("semantic", payload))


def _normalize(command: str) -> str:
    return " ".join(command.strip().upper().split())

