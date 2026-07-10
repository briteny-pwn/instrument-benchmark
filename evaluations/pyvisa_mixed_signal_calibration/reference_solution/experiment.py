"""Reference solution for the mixed-signal calibration instance."""

from __future__ import annotations

import json
from pathlib import Path

import pyvisa


AWG_POINTS = [-0.5, -0.25, 0.0, 0.25, 0.5]
TARGETS = {
    "MockAWG700": "awg",
    "MockScope900": "scope",
    "MockDMM650": "dmm",
}


class CalibrationBench:
    def __init__(self) -> None:
        self.rm = pyvisa.ResourceManager()
        self.opened = []
        self.instruments = {}
        self.identities = {}
        self.resources = {}

    def discover(self) -> None:
        for resource_name in self.rm.list_resources():
            inst = self.rm.open_resource(resource_name)
            self.opened.append(inst)
            inst.timeout = 12000
            inst.read_termination = "\n"
            inst.write_termination = "\n"
            identity = inst.query("*IDN?").strip()
            fields = identity.split(",")
            model = fields[1] if len(fields) > 1 else ""
            role = TARGETS.get(model)
            if role:
                self.instruments[role] = inst
                self.identities[role] = model
                self.resources[role] = resource_name
            if len(self.instruments) == 3:
                return
        raise RuntimeError("Could not discover all target instruments")

    def configure_awg(self) -> bool:
        awg = self.instruments["awg"]
        awg.write("*RST")
        awg.write_ascii_values("DATA:ARB CAL_RAMP,", AWG_POINTS)
        awg.write("FUNC:ARB CAL_RAMP")
        awg.write("VOLT 1.2")
        awg.write("VOLT:OFFS 0.0")
        awg.write("OUTP ON")
        return awg.query("OUTP?").strip() == "1"

    def read_dmm(self) -> list[float]:
        dmm = self.instruments["dmm"]
        dmm.write("*RST")
        dmm.write("CONF:VOLT:DC")
        dmm.write("VOLT:RANG 10")
        dmm.write("SAMP:COUN 4")
        dmm.write("INIT")
        return list(dmm.query_ascii_values("READ:VOLT?", separator=";"))

    def read_scope(self) -> tuple[list[int], list[float]]:
        scope = self.instruments["scope"]
        scope.write("*RST")
        scope.write("DATA:SOURCE CH1")
        scope.write("DATA:ENCODING RIBINARY")
        scope.write("DATA:WIDTH 1")
        scope.write("WFMOUTPRE:YMULT 0.02")
        scope.write("WFMOUTPRE:YOFF 80")
        scope.write("WFMOUTPRE:YZERO 0.0")
        raw_codes = [int(v) for v in scope.query_binary_values("CURVE?", datatype="B", expect_termination=False, chunk_size=4)]
        voltages = [(code - 80) * 0.02 + 0.0 for code in raw_codes]
        return raw_codes, voltages

    def close(self) -> None:
        for inst in self.opened:
            inst.close()
        self.rm.close()


def run_experiment(output_path: str = "result.json") -> dict:
    bench = CalibrationBench()
    try:
        bench.discover()
        output_enabled = bench.configure_awg()
        dmm_samples = bench.read_dmm()
        raw_codes, scope_voltages = bench.read_scope()
        dmm_average = sum(dmm_samples) / len(dmm_samples)
        p2p = max(scope_voltages) - min(scope_voltages)
        result = {
            "instruments": bench.identities,
            "resources": bench.resources,
            "awg_waveform": "CAL_RAMP",
            "awg_points": AWG_POINTS,
            "dmm_samples_v": dmm_samples,
            "dmm_average_v": dmm_average,
            "scope_raw_codes": raw_codes,
            "scope_voltages_v": scope_voltages,
            "scope_peak_to_peak_v": p2p,
            "calibration_passed": output_enabled and abs(dmm_average - 1.1995) <= 0.002 and abs(p2p - 1.2) <= 0.02,
        }
        if output_path:
            Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        bench.close()
