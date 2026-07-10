"""Trace wrapper for running scope candidate code against pyvisa-sim."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyvisa


RESOURCE_NAME = "TCPIP0::192.0.2.50::inst0::INSTR"
SIM_YAML = Path(__file__).resolve().parent / "pyvisa_sim" / "mockscope500.yaml"

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

        def open_resource(self, resource_name: str, *args: Any, **kwargs: Any) -> "TracedResource":
            TRACE.append(TraceEvent("open_resource", {"resource_name": resource_name}))
            resource = self._rm.open_resource(resource_name, *args, **kwargs)
            return TracedResource(resource)

        def close(self) -> None:
            TRACE.append(TraceEvent("close_resource_manager", {}))
            self._rm.close()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._rm, name)

    pyvisa.ResourceManager = TracedResourceManager  # type: ignore[assignment]


class TracedResource:
    def __init__(self, resource: Any) -> None:
        object.__setattr__(self, "_resource", resource)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"timeout", "read_termination", "write_termination"}:
            TRACE.append(TraceEvent("set_attribute", {"name": name, "value": value}))
        setattr(self._resource, name, value)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resource, name)

    def write(self, command: str, *args: Any, **kwargs: Any) -> Any:
        TRACE.append(TraceEvent("write", {"command": command}))
        result = self._resource.write(command, *args, **kwargs)
        _record_semantic(command, is_query=False)
        return result

    def query(self, command: str, *args: Any, **kwargs: Any) -> Any:
        TRACE.append(TraceEvent("query", {"command": command}))
        result = self._resource.query(command, *args, **kwargs)
        _record_semantic(command, is_query=True)
        return result

    def query_binary_values(self, command: str, *args: Any, **kwargs: Any) -> Any:
        TRACE.append(
            TraceEvent(
                "query_binary_values",
                {"command": command, "args": list(args), "kwargs": dict(kwargs)},
            )
        )
        result = self._resource.query_binary_values(command, *args, **kwargs)
        _record_semantic(command, is_query=True)
        return result

    def close(self) -> None:
        TRACE.append(TraceEvent("close_resource", {}))
        self._resource.close()


def reset_trace() -> None:
    TRACE.clear()


def _record_semantic(command: str, is_query: bool) -> None:
    normalized = _normalize(command)
    if normalized == "*IDN?":
        TRACE.append(TraceEvent("semantic", {"action": "identify"}))
        return
    if normalized == "*RST" and not is_query:
        TRACE.append(TraceEvent("semantic", {"action": "reset"}))
        return
    if normalized == "DATA:SOURCE CH1" and not is_query:
        TRACE.append(TraceEvent("semantic", {"action": "select_source", "source": "CH1"}))
        return
    if normalized == "DATA:ENCODING RIBINARY" and not is_query:
        TRACE.append(TraceEvent("semantic", {"action": "set_binary_encoding"}))
        return
    width_match = re.match(r"DATA:WIDTH\s+(?P<width>\d+)$", normalized)
    if width_match and not is_query:
        TRACE.append(TraceEvent("semantic", {"action": "set_data_width", "width": int(width_match.group("width"))}))
        return
    ymult_match = re.match(r"WFMOUTPRE:YMULT\s+(?P<value>[0-9.]+)$", normalized)
    if ymult_match and not is_query:
        TRACE.append(TraceEvent("semantic", {"action": "set_ymult", "value": float(ymult_match.group("value"))}))
        return
    yoff_match = re.match(r"WFMOUTPRE:YOFF\s+(?P<value>[0-9.]+)$", normalized)
    if yoff_match and not is_query:
        TRACE.append(TraceEvent("semantic", {"action": "set_yoff", "value": float(yoff_match.group("value"))}))
        return
    if normalized == "CURVE?" and is_query:
        TRACE.append(TraceEvent("semantic", {"action": "read_binary_waveform"}))


def _normalize(command: str) -> str:
    return " ".join(command.strip().upper().split())

