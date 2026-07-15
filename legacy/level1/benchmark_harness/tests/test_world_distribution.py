from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from benchmark_harness.paths import ROOT
from benchmark_harness.world_distribution import (
    distribution_scenarios,
    freeze_distribution,
    materialize_world,
)


PILOT_SPECS = (
    "pyvisa_dmm_ascii_average",
    "pyvisa_scope_binary_waveform",
    "pyvisa_multi_instrument_dut_validation",
)


def _load(path: Path) -> object:
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)


class WorldDistributionTests(unittest.TestCase):
    def test_pilot_worlds_are_reproducible_and_frozen(self) -> None:
        for instance_id in PILOT_SPECS:
            spec_path = ROOT / "evaluations" / "pyvisa" / instance_id / "spec.json"
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            scenarios = distribution_scenarios(spec)
            self.assertEqual(
                {scenario["world_group"] for scenario in scenarios},
                {"core", "generalization", "adversarial"},
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                outputs = freeze_distribution(spec_path, Path(tmpdir))
                for generated, scenario in zip(outputs, scenarios):
                    frozen = spec_path.parent / scenario["simulator"]
                    self.assertEqual(_load(generated), _load(frozen))

    def test_seed_controls_choice_without_global_random_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            template = root / "template.json"
            template.write_text('{"selected": -1}\n', encoding="utf-8")
            base_world = {
                "group": "core",
                "template": "template.json",
                "patches": [{"path": "/selected", "value": {"choice": list(range(1000))}}],
            }
            first = materialize_world(
                root, {**base_world, "seed": "repeatable"}, root / "first.json"
            )
            second = materialize_world(
                root, {**base_world, "seed": "repeatable"}, root / "second.json"
            )
            other = materialize_world(
                root, {**base_world, "seed": "different"}, root / "other.json"
            )
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertNotEqual(first.read_bytes(), other.read_bytes())


if __name__ == "__main__":
    unittest.main()
