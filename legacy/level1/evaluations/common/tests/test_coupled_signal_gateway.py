from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evaluations.common.coupled_signal_gateway import Gateway


class CoupledSignalGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        scenario = {
            "resources": [
                {"name": "PSU", "role": "psu", "idn": "Vendor,PSU,S1,1"},
                {"name": "SW", "role": "switch", "idn": "Vendor,SW,S2,1"},
                {"name": "AWG", "role": "awg", "idn": "Vendor,AWG,S3,1"},
                {"name": "SCOPE", "role": "scope", "idn": "Vendor,SCOPE,S4,1"},
                {"name": "DMM", "role": "dmm", "idn": "Vendor,DMM,S5,1"},
            ],
            "physics": {"required_paths": [101, 102], "nominal_supply_v": 5.0, "nominal_awg_amplitude_v": 1.2},
        }
        path = Path(self.tempdir.name) / "scenario.json"
        path.write_text(json.dumps(scenario), encoding="utf-8")
        self.gateway = Gateway(path)
        self.handles = {
            resource: self.gateway.dispatch({"op": "open", "resource": resource})["handle"]
            for resource in ("PSU", "SW", "AWG", "SCOPE", "DMM")
        }

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def write(self, resource: str, command: str) -> None:
        self.gateway.dispatch({"op": "write", "handle": self.handles[resource], "command": command})

    def test_downstream_observation_depends_on_all_source_states(self) -> None:
        self.write("PSU", ":SOUR:VOLT 5")
        self.write("PSU", ":OUTP ON")
        self.write("AWG", "DATA:ARB DUT,0,0.3,0.6")
        self.write("AWG", "FUNC:ARB DUT")
        self.write("AWG", "VOLT 1.2")
        self.write("AWG", "OUTP ON")
        self.write("DMM", "SAMP:COUN 3")

        disconnected = self.gateway.dispatch(
            {"op": "query", "handle": self.handles["DMM"], "command": "FETCH:VOLT?"}
        )["response"]
        self.assertEqual(disconnected, "0.000000,0.000000,0.000000")

        self.write("SW", "ROUT:CLOS (@101,102)")
        connected = self.gateway.dispatch(
            {"op": "query", "handle": self.handles["DMM"], "command": "FETCH:VOLT?"}
        )["response"]
        self.assertEqual(connected, "0.000000,0.300000,0.600000")

        self.write("PSU", ":SOUR:VOLT 2.5")
        reduced = self.gateway.dispatch(
            {"op": "query", "handle": self.handles["DMM"], "command": "FETCH:VOLT?"}
        )["response"]
        self.assertEqual(reduced, "0.000000,0.150000,0.300000")


if __name__ == "__main__":
    unittest.main()
