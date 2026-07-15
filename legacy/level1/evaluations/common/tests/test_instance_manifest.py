from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from evaluations.common.instance_manifest import (
    load_registry,
    validate_manifest,
    validate_registry,
)


ROOT = Path(__file__).resolve().parents[3]


class InstanceManifestTests(unittest.TestCase):
    def test_registry_covers_and_validates_every_instance(self) -> None:
        registry = load_registry(ROOT)
        self.assertEqual(len(registry), 19)
        self.assertEqual(validate_registry(ROOT), [])

    def test_missing_oracle_binding_is_rejected(self) -> None:
        manifest = load_registry(ROOT)["pyvisa/pyvisa_dc_power_supply_basic"]
        broken = copy.deepcopy(manifest)
        object.__setattr__(broken, "oracle_bindings", broken.oracle_bindings[:1])
        spec = json.loads(
            (
                ROOT
                / "evaluations/pyvisa/pyvisa_dc_power_supply_basic/spec.json"
            ).read_text(encoding="utf-8")
        )
        prompt = (
            ROOT / "instances/pyvisa/pyvisa_dc_power_supply_basic/prompt.md"
        ).read_text(encoding="utf-8")
        errors = validate_manifest(ROOT, broken, spec, prompt)
        self.assertTrue(any("lack oracle bindings" in error for error in errors))

    def test_prompt_spec_field_drift_is_rejected(self) -> None:
        manifest = load_registry(ROOT)["yaq/yaq_fake_sensor_stability_scan"]
        spec = json.loads(
            (
                ROOT
                / "evaluations/yaq/yaq_fake_sensor_stability_scan/spec.json"
            ).read_text(encoding="utf-8")
        )
        errors = validate_manifest(ROOT, manifest, spec, "# Task Goal\n")
        self.assertTrue(any("prompt does not declare result field" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
