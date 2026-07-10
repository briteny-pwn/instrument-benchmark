"""Reference solution for the PyVISA AWG ASCII upload instance."""

from __future__ import annotations

import json
from pathlib import Path

import pyvisa


RESOURCE_NAME = "USB0::0x9999::0x0100::AWG100001::INSTR"
POINTS = [0.0, 0.25, 0.5, 0.75, 1.0]


class MockAWG100:
    def __init__(self) -> None:
        self.rm = pyvisa.ResourceManager()
        self.inst = None

    def connect(self) -> None:
        self.inst = self.rm.open_resource(RESOURCE_NAME)
        self.inst.timeout = 6000
        self.inst.read_termination = "\n"
        self.inst.write_termination = "\n"

    def identify(self) -> str:
        return self.inst.query("*IDN?").strip()

    def configure(self) -> None:
        self.inst.write("*RST")
        self.inst.write_ascii_values("DATA:ARB RAMP,", POINTS)
        self.inst.write("FUNC:ARB RAMP")
        self.inst.write("VOLT 2.0")
        self.inst.write("OUTP ON")

    def state(self) -> tuple[str, bool]:
        waveform = self.inst.query("FUNC:ARB?").strip()
        output_enabled = self.inst.query("OUTP?").strip() == "1"
        return waveform, output_enabled

    def close(self) -> None:
        if self.inst is not None:
            self.inst.close()
        self.rm.close()


def run_experiment(output_path: str = "result.json") -> dict:
    awg = MockAWG100()
    try:
        awg.connect()
        identity = awg.identify()
        awg.configure()
        waveform, output_enabled = awg.state()
        result = {
            "instrument": identity.split(",")[1],
            "waveform": waveform,
            "points": POINTS,
            "point_count": len(POINTS),
            "amplitude_vpp": 2.0,
            "output_enabled": output_enabled,
        }
        if output_path:
            Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        awg.close()

