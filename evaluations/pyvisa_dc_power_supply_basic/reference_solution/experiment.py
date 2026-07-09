"""Reference solution for the PyVISA DC power supply access instance."""

from __future__ import annotations

import json
from pathlib import Path

import pyvisa


RESOURCE_NAME = "USB0::0x9999::0x0001::DP100001::INSTR"


class MockDP100PowerSupply:
    """Minimal driver for the MockDP100 power supply."""

    def __init__(self, resource_name: str = RESOURCE_NAME) -> None:
        self.resource_name = resource_name
        self.rm = None
        self.inst = None

    def connect(self) -> None:
        self.rm = pyvisa.ResourceManager()
        self.inst = self.rm.open_resource(self.resource_name)
        self.inst.timeout = 5000
        self.inst.read_termination = "\n"
        self.inst.write_termination = "\n"

    def identify(self) -> str:
        if self.inst is None:
            raise RuntimeError("Instrument is not connected")
        return self.inst.query("*IDN?")

    def set_voltage(self, channel: int, voltage: float) -> None:
        if self.inst is None:
            raise RuntimeError("Instrument is not connected")
        if channel != 1:
            raise ValueError("This experiment only supports CH1")
        if not 0 <= voltage <= 5:
            raise ValueError("Voltage must be in [0, 5] V")
        self.inst.write(f":SOURce{channel}:VOLTage {voltage}")

    def set_current_limit(self, channel: int, current: float) -> None:
        if self.inst is None:
            raise RuntimeError("Instrument is not connected")
        if channel != 1:
            raise ValueError("This experiment only supports CH1")
        if not 0 <= current <= 1:
            raise ValueError("Current limit must be in [0, 1] A")
        self.inst.write(f":SOURce{channel}:CURRent {current}")

    def output_on(self, channel: int) -> None:
        if self.inst is None:
            raise RuntimeError("Instrument is not connected")
        if channel != 1:
            raise ValueError("This experiment only supports CH1")
        self.inst.write(f":OUTPut CH{channel},ON")

    def measure_voltage(self, channel: int) -> float:
        if self.inst is None:
            raise RuntimeError("Instrument is not connected")
        if channel != 1:
            raise ValueError("This experiment only supports CH1")
        return float(self.inst.query(f":MEASure:VOLTage? CH{channel}"))

    def close(self) -> None:
        if self.inst is not None:
            self.inst.close()
            self.inst = None
        if self.rm is not None:
            self.rm.close()
            self.rm = None


def run_experiment(output_path: str | Path = "result.json") -> dict:
    psu = MockDP100PowerSupply()
    try:
        psu.connect()
        idn = psu.identify()
        psu.set_voltage(1, 3.3)
        psu.set_current_limit(1, 0.5)
        psu.output_on(1)
        measured_voltage = psu.measure_voltage(1)

        result = {
            "instrument": idn.split(",")[1],
            "channel": 1,
            "target_voltage_v": 3.3,
            "current_limit_a": 0.5,
            "measured_voltage_v": measured_voltage,
            "output_enabled": True,
        }
        Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        psu.close()


if __name__ == "__main__":
    run_experiment()

