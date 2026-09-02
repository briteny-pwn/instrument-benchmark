from __future__ import annotations

import os
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from instrument_benchmark.orchestrator import run_benchmark  # noqa: E402
from instrument_benchmark.environment import load_repository_paths  # noqa: E402


@unittest.skipUnless(
    os.environ.get("IAB_RUN_DOCKER_TESTS") == "1" and platform.system() == "Linux",
    "nested evaluator integration requires a native Linux Docker host",
)
class ContainerizedEvaluatorLinuxTests(unittest.TestCase):
    def test_official_path_runs_outer_evaluator_and_sibling_candidates(self) -> None:
        repositories = load_repository_paths(ROOT)
        evaluator = repositories.evaluator_repo_path
        instance = repositories.instances_repo_path
        owner = "containerized-evaluator-integration"
        with tempfile.TemporaryDirectory(prefix="iab-integration-") as directory:
            temporary = Path(directory)
            config = temporary / "run.yaml"
            report_path = temporary / "report.json"
            config.write_text(
                yaml.safe_dump(
                    {
                        "schema_version": 3,
                        "run_id": owner,
                        "source_id": "pyvisa",
                        "instance_id": "pyvisa_dut_validation_v1",
                        "evaluator_id": "pyvisa_dut_validation_v1",
                        "candidate_path": str(
                            evaluator
                            / "sources/pyvisa/pyvisa_dut_validation_v1/reference/solution.py"
                        ),
                        "report_path": str(report_path),
                        "timeout_seconds": 30,
                        "max_output_bytes": 1_048_576,
                        "repeated_worlds": 1,
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
                        allow_dirty=True,
                    )
                outer = report["orchestration"]["evaluator_container"]
                self.assertEqual(outer["network_mode"], "none")
                self.assertTrue(outer["readonly_rootfs"])
                self.assertEqual(outer["user"], "11001:11001")
                self.assertIn("ALL", outer["cap_drop"])
                self.assertIn("no-new-privileges", outer["security_options"])
                self.assertTrue(outer["cleanup_succeeded"])
                self.assertEqual(len(report["worlds"]), 10)
                self.assertTrue(
                    all(
                        world["container_evidence"]["cleanup_succeeded"]
                        for world in report["worlds"]
                    )
                )
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
