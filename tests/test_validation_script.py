from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.validate_distributed_benchmark import (
    _adversarial_cases,
    _v2_invariants,
)


class FormalValidationScriptTests(unittest.TestCase):
    def test_v2_invariants_require_literal_and_complete_sibling_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "solution.py"
            reference.write_text(
                'import pyvisa\nrm = pyvisa.ResourceManager("@iab")\n'
            )
            config = SimpleNamespace(
                evaluator_id="pyvisa_dut_validation_v2",
                candidate_path=reference,
            )
            world = {
                "candidate_container_evidence": {
                    "cleanup_succeeded": True,
                },
                "sim_container_evidence": {
                    "cleanup_succeeded": True,
                    "image_digest": "sha256:evaluator",
                },
                "sim_journal_evidence": {
                    "event_count": 2,
                    "events": [
                        {"kind": "lifecycle.finalized"},
                        {"kind": "lifecycle.exit"},
                    ],
                },
            }
            report = {
                "schema_version": 2,
                "evaluator": {"id": "pyvisa_dut_validation_v2"},
                "infrastructure_valid": True,
                "retry_eligible": False,
                "worlds": [world.copy() for _ in range(19)],
                "orchestration": {
                    "evaluator_image": {"image_id": "sha256:evaluator"},
                    "evaluator_container": {
                        "image_id": "sha256:evaluator"
                    },
                },
            }
            self.assertTrue(_v2_invariants(report, config))
            report["worlds"][0]["sim_journal_evidence"] = {
                "event_count": 0,
                "events": [],
            }
            self.assertFalse(_v2_invariants(report, config))

    def test_v2_adversarial_contract_keeps_protocol_and_leak_cases(self) -> None:
        cases = _adversarial_cases(
            Path("/unused"), "pyvisa_dut_validation_v2"
        )
        self.assertEqual(
            [case["submission"] for case in cases],
            ["negatives/bad_protocol.py", "negatives/leaked_sessions.py"],
        )
        self.assertEqual(
            [case["failed_gates"] for case in cases],
            [["no_forbidden_access"], ["active_close_all"]],
        )
        self.assertEqual(
            [case["expected_status"] for case in cases],
            ["completed", "invalid_result"],
        )


if __name__ == "__main__":
    unittest.main()
