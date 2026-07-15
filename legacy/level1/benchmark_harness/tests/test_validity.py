from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from benchmark_harness.validity import (
    analyze,
    import_baselines,
    sensitivity,
    write_jsonl,
)
from benchmark_harness.run_store import _release_inputs


def _record(
    system: str,
    item: str,
    trial: str,
    passed: bool,
    *,
    scenario_rate: float,
    task_score: float,
) -> dict:
    return {
        "protocol_version": 1,
        "system_id": system,
        "item_id": item,
        "trial_id": trial,
        "backend": "state_machine",
        "capabilities": ["task_success"],
        "passed": passed,
        "score": task_score,
        "hidden_scenario_pass_rate": scenario_rate,
        "dimension_scores": {"task_success": task_score, "safety": 1.0},
        "rubric": {"task_success": 0.75, "safety": 0.25},
        "pass_threshold": 0.8,
    }


class ValidityAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            _record("a", "one", "a1", True, scenario_rate=1.0, task_score=1.0),
            _record("a", "one", "a2", False, scenario_rate=0.5, task_score=0.7),
            _record("a", "two", "a3", True, scenario_rate=1.0, task_score=0.9),
            _record("b", "one", "b1", False, scenario_rate=0.0, task_score=0.4),
            _record("b", "two", "b2", True, scenario_rate=2 / 3, task_score=0.85),
        ]

    def test_analysis_reports_macro_rates_groups_and_paired_bootstrap(self) -> None:
        report = analyze(self.records, bootstrap_samples=100, seed=9)
        self.assertEqual(report["status"], "complete")
        self.assertAlmostEqual(report["systems"]["a"]["MIPR"], 0.75)
        self.assertAlmostEqual(report["systems"]["a"]["MHSPR"], 0.875)
        self.assertIn("state_machine", report["systems"]["a"]["by_backend"])
        self.assertEqual(report["paired_comparisons"][0]["paired_items"], 2)
        self.assertEqual(report["item_metrics"]["one"]["test_retest_pairs"], 1)

    def test_empty_analysis_is_explicitly_blocked(self) -> None:
        report = analyze([])
        self.assertEqual(report["status"], "blocked_no_data")

    def test_sensitivity_rescores_thresholds_and_weights(self) -> None:
        report = sensitivity(self.records, [0.8, 0.9], [-0.2, 0.2])
        self.assertEqual(report["status"], "complete")
        self.assertEqual(len(report["threshold_sensitivity"]), 2)
        self.assertEqual(len(report["rubric_weight_sensitivity"]), 4)

    def test_jsonl_round_trip_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "records.jsonl"
            write_jsonl(path, self.records)
            loaded = import_baselines([path])
        self.assertEqual(len(loaded), len(self.records))
        self.assertIs(loaded[0]["passed"], True)

    def test_release_inputs_bind_spec_scenarios_generators_and_dependencies(self) -> None:
        inputs, seeds = _release_inputs("pyvisa", "pyvisa_dc_power_supply_basic")
        self.assertEqual(len(inputs["spec"]["sha256"]), 64)
        self.assertGreaterEqual(len(inputs["scenarios"]), 3)
        self.assertGreaterEqual(len(inputs["generators"]), 3)
        self.assertIn(inputs["dependency_lock"]["status"], {"locked", "missing"})
        self.assertTrue(inputs["dependency_manifests"])
        self.assertEqual(seeds["authoring"], "power-authoring-v1")


if __name__ == "__main__":
    unittest.main()
