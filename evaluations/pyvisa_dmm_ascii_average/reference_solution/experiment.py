"""Reference solution for the PyVISA DMM ASCII average instance."""

from __future__ import annotations

import json
from pathlib import Path

import pyvisa


RESOURCE_NAME = "GPIB0::12::INSTR"


class MockDMM2000:
    """Minimal access layer for MockDMM2000."""

    def __init__(self, resource_name: str = RESOURCE_NAME) -> None:
        self.resource_name = resource_name
        self.rm = None
        self.inst = None

    def connect(self) -> None:
        self.rm = pyvisa.ResourceManager()
        self.inst = self.rm.open_resource(self.resource_name)
        self.inst.timeout = 10000
        self.inst.read_termination = "\n"
        self.inst.write_termination = "\n"

    def identify(self) -> str:
        if self.inst is None:
            raise RuntimeError("Instrument is not connected")
        return self.inst.query("*IDN?")

    def reset(self) -> None:
        if self.inst is None:
            raise RuntimeError("Instrument is not connected")
        self.inst.write("*RST")

    def configure_dc_voltage(self, voltage_range: float, resolution: float) -> None:
        if self.inst is None:
            raise RuntimeError("Instrument is not connected")
        self.inst.write("CONF:VOLT:DC")
        self.inst.write(f"VOLT:RANG {voltage_range:g}")
        self.inst.write(f"VOLT:RES {resolution:g}")

    def set_sample_count(self, count: int) -> None:
        if self.inst is None:
            raise RuntimeError("Instrument is not connected")
        self.inst.write(f"SAMP:COUN {count}")

    def initiate(self) -> None:
        if self.inst is None:
            raise RuntimeError("Instrument is not connected")
        self.inst.write("INIT")

    def read_trace_data(self) -> list[float]:
        if self.inst is None:
            raise RuntimeError("Instrument is not connected")
        return list(self.inst.query_ascii_values("TRACE:DATA?"))

    def clear_trace(self) -> None:
        if self.inst is None:
            raise RuntimeError("Instrument is not connected")
        self.inst.write("TRACE:CLEAR")

    def close(self) -> None:
        if self.inst is not None:
            self.inst.close()
            self.inst = None
        if self.rm is not None:
            self.rm.close()
            self.rm = None


def run_experiment(output_path: str | Path = "result.json") -> dict:
    dmm = MockDMM2000()
    try:
        dmm.connect()
        idn = dmm.identify()
        dmm.reset()
        dmm.configure_dc_voltage(10, 0.001)
        dmm.set_sample_count(5)
        dmm.initiate()
        samples = dmm.read_trace_data()
        dmm.clear_trace()

        result = {
            "instrument": idn.split(",")[1],
            "measurement": "dc_voltage",
            "sample_count": len(samples),
            "samples_v": samples,
            "average_voltage_v": sum(samples) / len(samples),
            "unit": "V",
        }
        Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        dmm.close()


if __name__ == "__main__":
    run_experiment()
