"""Fake PyVISA module used by the grader.

It records access behavior and simulates a small DC power supply state machine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


RESOURCE_NAME = "USB0::0x9999::0x0001::DP100001::INSTR"
RESOURCE_MANAGERS: list["ResourceManager"] = []


@dataclass
class TraceEvent:
    kind: str
    payload: dict[str, Any]


@dataclass
class FakeInstrumentState:
    voltage: dict[int, float] = field(default_factory=lambda: {1: 0.0, 2: 0.0})
    current: dict[int, float] = field(default_factory=lambda: {1: 0.0, 2: 0.0})
    output: dict[int, bool] = field(default_factory=lambda: {1: False, 2: False})


class FakeVisaError(Exception):
    pass


class FakeResource:
    def __init__(self, resource_name: str, trace: list[TraceEvent]) -> None:
        self.resource_name = resource_name
        self.trace = trace
        self.state = FakeInstrumentState()
        self.closed = False
        self.timeout = None
        self.read_termination = None
        self.write_termination = None

    def _record(self, kind: str, **payload: Any) -> None:
        self.trace.append(TraceEvent(kind, payload))

    def write(self, command: str) -> int:
        self._record("write", command=command)
        self._apply_command(command)
        return len(command)

    def query(self, command: str) -> str:
        self._record("query", command=command)
        return self._answer_query(command)

    def close(self) -> None:
        self.closed = True
        self._record("close_resource")

    def _apply_command(self, command: str) -> None:
        normalized = _normalize(command)

        voltage_match = re.match(r"(?::?SOUR(?:CE)?(?P<ch>\d+):VOLT(?:AGE)?|VOLT)\s+(?P<value>[0-9.]+)(?:,CH(?P<alt_ch>\d+))?$", normalized)
        if voltage_match:
            channel = int(voltage_match.group("ch") or voltage_match.group("alt_ch") or 1)
            value = float(voltage_match.group("value"))
            if not 0 <= value <= 5:
                raise FakeVisaError("Voltage is outside safe range")
            self.state.voltage[channel] = value
            self._record("semantic", action="set_voltage", channel=channel, value=value, unit="V")
            return

        current_match = re.match(r"(?::?SOUR(?:CE)?(?P<ch>\d+):CURR(?:ENT)?|CURR)\s+(?P<value>[0-9.]+)(?:,CH(?P<alt_ch>\d+))?$", normalized)
        if current_match:
            channel = int(current_match.group("ch") or current_match.group("alt_ch") or 1)
            value = float(current_match.group("value"))
            if not 0 <= value <= 1:
                raise FakeVisaError("Current limit is outside safe range")
            self.state.current[channel] = value
            self._record("semantic", action="set_current_limit", channel=channel, value=value, unit="A")
            return

        output_match = re.match(r":?OUTP(?:UT)?\s+(?:CH(?P<ch1>\d+),(?P<state1>ON|OFF)|(?P<state2>ON|OFF),CH(?P<ch2>\d+))$", normalized)
        if output_match:
            channel = int(output_match.group("ch1") or output_match.group("ch2"))
            enabled = (output_match.group("state1") or output_match.group("state2")) == "ON"
            self.state.output[channel] = enabled
            self._record("semantic", action="enable_output", channel=channel, value=enabled)
            return

        raise FakeVisaError(f"Unsupported command: {command}")

    def _answer_query(self, command: str) -> str:
        normalized = _normalize(command)
        if normalized == "*IDN?":
            self._record("semantic", action="identify")
            return "Mock Instruments,MockDP100,DP100001,1.0"

        measure_match = re.match(r":?(?:MEAS(?:URE)?:VOLT(?:AGE)?\?|MEAS\?)\s+CH(?P<ch>\d+)$", normalized)
        if measure_match:
            channel = int(measure_match.group("ch"))
            self._record("semantic", action="measure_voltage", channel=channel)
            if not self.state.output[channel]:
                return "0.0"
            return f"{self.state.voltage[channel] - 0.002:.3f}"

        raise FakeVisaError(f"Unsupported query: {command}")


class ResourceManager:
    def __init__(self) -> None:
        self.trace: list[TraceEvent] = []
        self.resource: FakeResource | None = None
        self.closed = False
        RESOURCE_MANAGERS.append(self)

    def open_resource(self, resource_name: str) -> FakeResource:
        self.trace.append(TraceEvent("open_resource", {"resource_name": resource_name}))
        if resource_name != RESOURCE_NAME:
            raise FakeVisaError(f"Unexpected resource name: {resource_name}")
        self.resource = FakeResource(resource_name, self.trace)
        return self.resource

    def close(self) -> None:
        self.closed = True
        self.trace.append(TraceEvent("close_resource_manager", {}))


def _normalize(command: str) -> str:
    return " ".join(command.strip().upper().split())
