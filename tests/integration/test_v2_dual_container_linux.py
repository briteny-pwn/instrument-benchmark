from __future__ import annotations

import os
import platform
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from instrument_benchmark.contracts import validate_evaluator_report  # noqa: E402
from instrument_benchmark.environment import load_repository_paths  # noqa: E402
from instrument_benchmark.orchestrator import run_benchmark  # noqa: E402


def _container_owner() -> str:
    return os.environ.get("IAB_CONTAINER_OWNER") or (
        f"instrument-v2-formal-{uuid.uuid4().hex}"
    )


class V2FormalOwnerTests(unittest.TestCase):
    def test_owner_inherits_ci_value_and_local_fallback_is_unique(self) -> None:
        with patch.dict(
            os.environ, {"IAB_CONTAINER_OWNER": "distributed-v2-123-1"}
        ):
            self.assertEqual(_container_owner(), "distributed-v2-123-1")
        with patch.dict(os.environ, {}, clear=True):
            first = _container_owner()
            second = _container_owner()
        self.assertRegex(first, r"^instrument-v2-formal-[0-9a-f]{32}$")
        self.assertNotEqual(first, second)


@unittest.skipUnless(
    os.environ.get("IAB_RUN_DOCKER_TESTS") == "1"
    and platform.system() == "Linux",
    "formal v2 chain requires native Linux Docker",
)
class V2FormalDualContainerLinuxTests(unittest.TestCase):
    def test_reference_passes_all_nineteen_worlds_with_complete_evidence(
        self,
    ) -> None:
        repositories = load_repository_paths(ROOT)
        evaluator = repositories.evaluator_repo_path
        instance = repositories.instances_repo_path
        reference = (
            evaluator
            / "sources"
            / "pyvisa"
            / "pyvisa_dut_validation_v2"
            / "reference"
            / "solution.py"
        )
        self.assertIn(
            'pyvisa.ResourceManager("@iab")',
            reference.read_text(encoding="utf-8"),
        )
        owner = _container_owner()
        with tempfile.TemporaryDirectory(prefix="iab-v2-formal-") as directory:
            temporary = Path(directory)
            config = temporary / "run.yaml"
            report_path = temporary / "report.json"
            config.write_text(
                yaml.safe_dump(
                    {
                        "schema_version": 3,
                        "run_id": owner,
                        "source_id": "pyvisa",
                        "instance_id": "pyvisa_dut_validation_v2",
                        "evaluator_id": "pyvisa_dut_validation_v2",
                        "candidate_path": (
                            "sources/pyvisa/pyvisa_dut_validation_v2/"
                            "reference/solution.py"
                        ),
                        "report_path": str(report_path),
                        "timeout_seconds": 30,
                        "max_output_bytes": 1_048_576,
                        "repeated_worlds": 10,
                        "repeated_base_seed": 40_000,
                        "container_protocol_version": 1,
                        "image_mode": "locked",
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            try:
                with patch.dict(os.environ, {"IAB_CONTAINER_OWNER": owner}):
                    report = run_benchmark(
                        config,
                        instrument_checkout=ROOT,
                        repository_paths=repositories,
                        allow_dirty=False,
                    )
                validate_evaluator_report(
                    report,
                    "pyvisa",
                    "pyvisa_dut_validation_v2",
                    expected_run_id=owner,
                )
                self.assertEqual(report["schema_version"], 3)
                self.assertEqual(report["score"], 100)
                self.assertTrue(report["strict_pass"])
                self.assertTrue(report["infrastructure_valid"])
                self.assertFalse(report["retry_eligible"])
                self.assertEqual(len(report["worlds"]), 19)
                self.assertEqual(
                    set(report["provenance"]),
                    {"instrument", "instance", "evaluator"},
                )
                self.assertTrue(
                    all(
                        not value["dirty"]
                        for value in report["provenance"].values()
                    )
                )
                orchestration = report["orchestration"]
                outer = orchestration["evaluator_container"]
                evaluator_image_id = orchestration["evaluator_image"]["image_id"]
                candidate_image_id = orchestration["container_provenance"][
                    "image_digest"
                ]
                self.assertEqual(outer["image_id"], evaluator_image_id)
                self.assertEqual(outer["network_mode"], "none")
                self.assertTrue(outer["readonly_rootfs"])
                self.assertEqual(outer["user"], "11001:11001")
                self.assertIn("ALL", outer["cap_drop"])
                self.assertIn(
                    "no-new-privileges", outer["security_options"]
                )
                self.assertTrue(outer["cleanup_succeeded"])
                self.assertTrue(
                    orchestration["container_provenance"][
                        "docker_engine_version"
                    ]
                )
                all_ids = {outer["container_id"]}
                for world in report["worlds"]:
                    candidate = world["candidate_container_evidence"]
                    sim = world["sim_container_evidence"]
                    journal = world["sim_journal_evidence"]
                    self.assertEqual(candidate["image_digest"], candidate_image_id)
                    self.assertEqual(sim["image_digest"], evaluator_image_id)
                    self.assertEqual(candidate["user"], "10001:10001")
                    self.assertEqual(sim["user"], "11001:11001")
                    for evidence in (candidate, sim):
                        self.assertEqual(evidence["network_mode"], "none")
                        self.assertTrue(evidence["readonly_rootfs"])
                        self.assertTrue(evidence["cleanup_succeeded"])
                    self.assertNotEqual(
                        candidate["container_id"], sim["container_id"]
                    )
                    all_ids.update(
                        (candidate["container_id"], sim["container_id"])
                    )
                    self.assertEqual(journal["event_count"], len(journal["events"]))
                    self.assertEqual(
                        journal["final_hash"], journal["events"][-1]["event_hash"]
                    )
                    self.assertEqual(
                        journal["events"][0]["kind"], "lifecycle.start"
                    )
                    self.assertEqual(
                        journal["events"][-1]["kind"], "lifecycle.exit"
                    )
                    self.assertIn(
                        "lifecycle.finalized",
                        {event["kind"] for event in journal["events"]},
                    )
                    self.assertTrue(journal["post_cleanup_snapshot"]["safe"])
                self.assertEqual(len(all_ids), 39)
                self.assertTrue(report_path.is_file())
            finally:
                stale = subprocess.run(
                    [
                        "docker",
                        "ps",
                        "-a",
                        "--filter",
                        f"label=iab.owner={owner}",
                        "--format",
                        "{{.ID}}",
                    ],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(stale.returncode, 0, stale.stderr)
                self.assertEqual(stale.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
