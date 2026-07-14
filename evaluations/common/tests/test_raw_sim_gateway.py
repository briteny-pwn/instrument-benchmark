from __future__ import annotations

import unittest

from evaluations.common.raw_sim_gateway import Gateway, _parse_snapshot_value


class SnapshotParsingTests(unittest.TestCase):
    def test_parses_numeric_and_output_state(self) -> None:
        self.assertEqual(_parse_snapshot_value("3.300", "float"), 3.3)
        self.assertTrue(_parse_snapshot_value("ON", "bool_on_off"))
        self.assertFalse(_parse_snapshot_value("OFF", "bool_on_off"))

    def test_query_guard_requires_cross_instrument_write_evidence(self) -> None:
        gateway = object.__new__(Gateway)
        gateway.query_guards = [
            {
                "command": "READ?",
                "requires_write_patterns": [r"^OUTP ON$", r"^DATA:ARB .+$"],
                "requires_latest_write": [
                    {"family_pattern": r"^OUTP (?:ON|OFF)$", "required_pattern": r"^OUTP ON$"}
                ],
            }
        ]
        gateway.observed_writes = ["DATA:ARB RAMP,0,1"]

        with self.assertRaises(RuntimeError):
            gateway._enforce_query_guards("READ?")

        gateway.observed_writes.append("OUTP ON")
        gateway._enforce_query_guards("READ?")

        gateway.observed_writes.append("OUTP OFF")
        with self.assertRaises(RuntimeError):
            gateway._enforce_query_guards("READ?")


if __name__ == "__main__":
    unittest.main()
