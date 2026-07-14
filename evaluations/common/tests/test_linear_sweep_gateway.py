from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evaluations.common.linear_sweep_gateway import Gateway


class LinearSweepGatewayTests(unittest.TestCase):
    def test_measurement_uses_actual_source_state_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scenario.json"
            path.write_text(
                json.dumps(
                    {
                        "resources": [
                            {"name": "SRC", "role": "source", "idn": "V,Source,S,1"},
                            {"name": "DMM", "role": "dmm", "idn": "V,DMM,D,1"},
                        ],
                        "physics": {"slope": 2.0, "intercept_v": 0.01},
                    }
                ),
                encoding="utf-8",
            )
            gateway = Gateway(path)
            source = gateway.dispatch({"op": "open", "resource": "SRC"})["handle"]
            dmm = gateway.dispatch({"op": "open", "resource": "DMM"})["handle"]

            off = gateway.dispatch({"op": "query", "handle": dmm, "command": "READ:VOLT? 0.3"})
            self.assertEqual(float(off["response"]), 0.0)

            gateway.dispatch({"op": "write", "handle": source, "command": "OUTP ON"})
            gateway.dispatch({"op": "write", "handle": source, "command": "SOUR:GATE 0.2"})
            measured = gateway.dispatch({"op": "query", "handle": dmm, "command": "READ:VOLT? 0.3"})

            self.assertAlmostEqual(float(measured["response"]), 0.41)
            self.assertEqual(gateway.observations[-1]["requested_setpoint_v"], 0.3)
            self.assertEqual(gateway.observations[-1]["actual_setpoint_v"], 0.2)


if __name__ == "__main__":
    unittest.main()
