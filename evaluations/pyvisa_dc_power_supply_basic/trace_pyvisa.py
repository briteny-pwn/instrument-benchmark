"""Trace wrapper for running candidate code against pyvisa-sim.

The wrapper keeps the public PyVISA API shape while redirecting ResourceManager
creation to the hidden pyvisa-sim YAML file when no explicit backend is passed.
It records connection, configuration, command, query, and cleanup events for
the grader.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyvisa


RESOURCE_NAME = "USB0::0x9999::0x0001::DP100001::INSTR"
SIM_YAML = Path(__file__).resolve().parent / "pyvisa_sim" / "mockdp100.yaml"

TRACE: list["TraceEvent"] = []


@dataclass
class TraceEvent:
    kind: str
    payload: dict[str, Any]


def install() -> None:
    """Patch pyvisa.ResourceManager for the current Python process."""
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
    """Proxy around a PyVISA resource that records the access process."""

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

    voltage_match = re.match(
        r"(?::?SOUR(?:CE)?(?P<ch>\d+):VOLT(?:AGE)?|VOLT)\s+"
        r"(?P<value>[0-9.]+)(?:,CH(?P<alt_ch>\d+))?$",
        normalized,
    )
    if voltage_match and not is_query:
        channel = int(voltage_match.group("ch") or voltage_match.group("alt_ch") or 1)
        TRACE.append(
            TraceEvent(
                "semantic",
                {
                    "action": "set_voltage",
                    "channel": channel,
                    "value": float(voltage_match.group("value")),
                    "unit": "V",
                },
            )
        )
        return

    current_match = re.match(
        r"(?::?SOUR(?:CE)?(?P<ch>\d+):CURR(?:ENT)?|CURR)\s+"
        r"(?P<value>[0-9.]+)(?:,CH(?P<alt_ch>\d+))?$",
        normalized,
    )
    if current_match and not is_query:
        channel = int(current_match.group("ch") or current_match.group("alt_ch") or 1)
        TRACE.append(
            TraceEvent(
                "semantic",
                {
                    "action": "set_current_limit",
                    "channel": channel,
                    "value": float(current_match.group("value")),
                    "unit": "A",
                },
            )
        )
        return

    output_match = re.match(
        r":?OUTP(?:UT)?\s+"
        r"(?:CH(?P<ch1>\d+),(?P<state1>ON|OFF)|(?P<state2>ON|OFF),CH(?P<ch2>\d+))$",
        normalized,
    )
    if output_match and not is_query:
        channel = int(output_match.group("ch1") or output_match.group("ch2"))
        enabled = (output_match.group("state1") or output_match.group("state2")) == "ON"
        TRACE.append(
            TraceEvent(
                "semantic",
                {"action": "enable_output", "channel": channel, "value": enabled},
            )
        )
        return

    measure_match = re.match(
        r":?(?:MEAS(?:URE)?:VOLT(?:AGE)?\?|MEAS\?)\s+CH(?P<ch>\d+)$",
        normalized,
    )
    if measure_match and is_query:
        TRACE.append(
            TraceEvent(
                "semantic",
                {"action": "measure_voltage", "channel": int(measure_match.group("ch"))},
            )
        )


def _normalize(command: str) -> str:
    return " ".join(command.strip().upper().split())
