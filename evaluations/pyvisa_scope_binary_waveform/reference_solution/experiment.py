"""Reference solution for the PyVISA scope binary waveform instance."""

from __future__ import annotations

import json
from pathlib import Path

import pyvisa


RESOURCE_NAME = "TCPIP0::192.0.2.50::inst0::INSTR"


class MockScope500:
    def __init__(self) -> None:
        self.rm = pyvisa.ResourceManager()
        self.inst = None

    def connect(self) -> None:
        self.inst = self.rm.open_resource(RESOURCE_NAME)
        self.inst.timeout = 8000
        self.inst.read_termination = "\n"
        self.inst.write_termination = "\n"

    def identify(self) -> str:
        return self.inst.query("*IDN?").strip()

    def configure(self) -> None:
        self.inst.write("*RST")
        self.inst.write("DATA:SOURCE CH1")
        self.inst.write("DATA:ENCODING RIBINARY")
        self.inst.write("DATA:WIDTH 1")
        self.inst.write("WFMOUTPRE:YMULT 0.02")
        self.inst.write("WFMOUTPRE:YOFF 128")

    def read_waveform(self) -> list[int]:
        values = self.inst.query_binary_values("CURVE?", datatype="B", expect_termination=False)
        return [int(value) for value in values]

    def close(self) -> None:
        if self.inst is not None:
            self.inst.close()
        self.rm.close()


def run_experiment(output_path: str = "result.json") -> dict:
    scope = MockScope500()
    try:
        scope.connect()
        identity = scope.identify()
        scope.configure()
        raw_codes = scope.read_waveform()
        ymult = 0.02
        yoff = 128
        voltages = [(code - yoff) * ymult for code in raw_codes]
        result = {
            "instrument": identity.split(",")[1],
            "source": "CH1",
            "sample_count": len(raw_codes),
            "raw_codes": raw_codes,
            "voltage_scale_v": ymult,
            "voltage_offset_code": yoff,
            "voltages_v": voltages,
            "unit": "V",
        }
        if output_path:
            Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        scope.close()

