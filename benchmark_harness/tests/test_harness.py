from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmark_harness.authoring import materialize
from benchmark_harness.linting import lint_all
from benchmark_harness.paths import ROOT
from evaluations.common import grader_core


class VisibleBoundaryTests(unittest.TestCase):
    def test_all_instances_pass_leakage_lint(self) -> None:
        self.assertEqual(lint_all(ROOT), {})


class AuthoringScenarioTests(unittest.TestCase):
    def test_every_instance_materializes_a_distinct_unscored_scenario(self) -> None:
        specs = sorted((ROOT / "evaluations").glob("*/*/spec.json"))
        self.assertEqual(len(specs), 19)
        with tempfile.TemporaryDirectory() as tmpdir:
            for index, spec_path in enumerate(specs):
                spec = json.loads(spec_path.read_text(encoding="utf-8"))
                authoring = spec["authoring"]
                base = spec_path.parent / authoring["base_simulator"]
                output = materialize(base, Path(tmpdir) / str(index), authoring["seed"])
                self.assertNotEqual(output.read_bytes(), base.read_bytes(), spec_path.parent.name)
                if output.suffix == ".json":
                    data = json.loads(output.read_text(encoding="utf-8"))
                    self.assertFalse(data["_authoring"]["scored"])


class CollectedEvidenceTests(unittest.TestCase):
    def test_collected_trace_is_scored_without_loading_candidate(self) -> None:
        spec = {
            "instance_id": "isolated",
            "spec_version": 2,
            "checks": [
                {
                    "name": "value_binding",
                    "type": "result_trace_binding",
                    "dimension": "task_success",
                    "result_path": "$.value",
                    "event_kind": "query",
                    "payload_field": "response",
                },
                {
                    "name": "access",
                    "type": "anti_hardcode",
                    "dimension": "instrument_access",
                    "requires": ["socket_connect", "query"],
                }
            ],
        }
        report = grader_core.grade_collected_scenario(
            spec=spec,
            result={"value": "1"},
            trace=[
                {"kind": "socket_connect", "payload": {}},
                {"kind": "query", "payload": {"response": "1"}},
            ],
            sim_state={},
            execution_score=1.0,
            forbidden_score=1.0,
        )
        self.assertEqual(report["scores"]["instrument_access"], 1.0)


if __name__ == "__main__":
    unittest.main()
