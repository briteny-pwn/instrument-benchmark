"""Trace wrapper for running DMM candidate code against pyvisa-sim."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyvisa


RESOURCE_NAME = "GPIB0::12::INSTR"
SIM_YAML = Path(__file__).resolve().parent / "pyvisa_sim" / "mockdmm2000.yaml"

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
            TRACE.append(
                TraceEvent(
                    "resource_manager",
                    {"backend": str(backend_args[0]) if backend_args else ""},
                )
            )

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

    def query_ascii_values(self, command: str, *args: Any, **kwargs: Any) -> Any:
        TRACE.append(TraceEvent("query_ascii_values", {"command": command}))
        result = self._resource.query_ascii_values(command, *args, **kwargs)
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

    if normalized == "CONF:VOLT:DC" and not is_query:
        TRACE.append(TraceEvent("semantic", {"action": "configure_dc_voltage"}))
        return

    range_match = re.match(r"VOLT:RANG\s+(?P<range>[0-9.]+)$", normalized)
    if range_match and not is_query:
        TRACE.append(
            TraceEvent(
                "semantic",
                {
                    "action": "set_voltage_range",
                    "range_v": float(range_match.group("range")),
                },
            )
        )
        return

    resolution_match = re.match(r"VOLT:RES\s+(?P<resolution>[0-9.]+)$", normalized)
    if resolution_match and not is_query:
        TRACE.append(
            TraceEvent(
                "semantic",
                {
                    "action": "set_voltage_resolution",
                    "resolution_v": float(resolution_match.group("resolution")),
                },
            )
        )
        return

    sample_match = re.match(r"SAMP(?:LE)?:COUN(?:T)?\s+(?P<count>\d+)$", normalized)
    if sample_match and not is_query:
        TRACE.append(
            TraceEvent(
                "semantic",
                {"action": "set_sample_count", "count": int(sample_match.group("count"))},
            )
        )
        return

    if normalized == "INIT" and not is_query:
        TRACE.append(TraceEvent("semantic", {"action": "initiate"}))
        return
    if normalized == "TRACE:DATA?" and is_query:
        TRACE.append(TraceEvent("semantic", {"action": "read_trace_data"}))
        return
    if normalized == "TRACE:CLEAR" and not is_query:
        TRACE.append(TraceEvent("semantic", {"action": "clear_trace"}))


def _normalize(command: str) -> str:
    return " ".join(command.strip().upper().split())
