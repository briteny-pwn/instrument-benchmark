"""Model-visible PyVISA-compatible simulation for MockDP100.

This file exists to document the simulated environment. The benchmark runner
may inject this module as `pyvisa` when executing a candidate solution.
"""

from __future__ import annotations

import re


RESOURCE_NAME = "USB0::0x9999::0x0001::DP100001::INSTR"


class VisaIOError(Exception):
    pass


class SimulatedResource:
    def __init__(self, resource_name: str) -> None:
        self.resource_name = resource_name
        self.timeout = None
        self.read_termination = None
        self.write_termination = None
        self.closed = False
        self.voltage = {1: 0.0, 2: 0.0}
        self.current = {1: 0.0, 2: 0.0}
        self.output = {1: False, 2: False}

    def write(self, command: str) -> int:
        normalized = _normalize(command)

        voltage_match = re.match(
            r":?SOURCE(?P<channel>\d+):VOLTAGE (?P<value>[0-9.]+)$",
            normalized,
        )
        if voltage_match:
            channel = int(voltage_match.group("channel"))
            value = float(voltage_match.group("value"))
            if not 0 <= value <= 5:
                raise VisaIOError("Voltage is outside allowed range")
            self.voltage[channel] = value
            return len(command)

        current_match = re.match(
            r":?SOURCE(?P<channel>\d+):CURRENT (?P<value>[0-9.]+)$",
            normalized,
        )
        if current_match:
            channel = int(current_match.group("channel"))
            value = float(current_match.group("value"))
            if not 0 <= value <= 1:
                raise VisaIOError("Current limit is outside allowed range")
            self.current[channel] = value
            return len(command)

        output_match = re.match(
            r":?OUTPUT CH(?P<channel>\d+),(?P<state>ON|OFF)$",
            normalized,
        )
        if output_match:
            channel = int(output_match.group("channel"))
            self.output[channel] = output_match.group("state") == "ON"
            return len(command)

        raise VisaIOError(f"Unsupported command: {command}")

    def query(self, command: str) -> str:
        normalized = _normalize(command)

        if normalized == "*IDN?":
            return "Mock Instruments,MockDP100,DP100001,1.0"

        measure_match = re.match(
            r":?MEASURE:VOLTAGE\? CH(?P<channel>\d+)$",
            normalized,
        )
        if measure_match:
            channel = int(measure_match.group("channel"))
            if not self.output[channel]:
                return "0.0"
            return f"{self.voltage[channel] - 0.002:.3f}"

        raise VisaIOError(f"Unsupported query: {command}")

    def close(self) -> None:
        self.closed = True


class ResourceManager:
    def __init__(self) -> None:
        self.closed = False

    def open_resource(self, resource_name: str) -> SimulatedResource:
        if resource_name != RESOURCE_NAME:
            raise VisaIOError(f"Unknown resource: {resource_name}")
        return SimulatedResource(resource_name)

    def close(self) -> None:
        self.closed = True


def _normalize(command: str) -> str:
    return " ".join(command.strip().upper().split())

