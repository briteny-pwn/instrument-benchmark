from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from instrument_benchmark.contracts import (  # noqa: E402
    ContractError,
    load_run_config,
    repository_provenance,
    validate_dependencies,
)
from instrument_benchmark.orchestrator import run_benchmark  # noqa: E402


class DistributedOrchestratorTests(unittest.TestCase):
    def make_repo(self, root: Path, name: str) -> Path:
        path = root / name
        path.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=path,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=path,
            check=True,
        )
        (path / "README.md").write_text(name)
        subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True)
        return path

    def test_repository_provenance_rejects_dirty_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(Path(directory), "repo")
            provenance = repository_provenance(repo)
            self.assertEqual(provenance.branch, "main")
            self.assertEqual(len(provenance.commit), 40)
            (repo / "dirty.txt").write_text("dirty")
            with self.assertRaisesRegex(ContractError, "dirty"):
                repository_provenance(repo)
            self.assertEqual(
                repository_provenance(repo, allow_dirty=True).commit,
                provenance.commit,
            )

    def test_dependency_manifests_must_match_ids_and_protocol(self) -> None:
        instance = {
            "instance_id": "pyvisa_dut_validation_v1",
            "evaluator": {
                "id": "pyvisa_dut_validation_v1",
                "protocol_version": 1,
            },
        }
        evaluator = {
            "evaluator_id": "pyvisa_dut_validation_v1",
            "protocol_version": 1,
            "supported_instances": ["pyvisa_dut_validation_v1"],
        }
        validate_dependencies(instance, evaluator)
        evaluator["protocol_version"] = 2
        with self.assertRaisesRegex(ContractError, "protocol"):
            validate_dependencies(instance, evaluator)

    def test_run_config_resolves_paths_relative_to_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("instance", "evaluator"):
                (root / name).mkdir()
            (root / "solution.py").write_text("pass")
            config = root / "run.yaml"
            config.write_text(
                "\n".join(
                    (
                        "schema_version: 1",
                        "run_id: test",
                        "instance_checkout: instance",
                        "instance_id: pyvisa_dut_validation_v1",
                        "evaluator_checkout: evaluator",
                        "evaluator_id: pyvisa_dut_validation_v1",
                        "candidate_path: solution.py",
                        "report_path: report.json",
                        "timeout_seconds: 30",
                        "max_output_bytes: 65536",
                        "repeated_worlds: 10",
                        "repeated_base_seed: 40000",
                    )
                )
            )
            loaded = load_run_config(config)
            self.assertEqual(loaded.instance_checkout, (root / "instance").resolve())
            self.assertEqual(loaded.report_path, (root / "report.json").resolve())

    def test_fake_evaluator_is_invoked_through_json_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instrument = self.make_repo(root, "instrument")
            instance = self.make_repo(root, "instance")
            evaluator = self.make_repo(root, "evaluator")
            candidate = root / "solution.py"
            candidate.write_text("pass")

            visible = instance / "task.txt"
            visible.write_text("visible")
            digest = hashlib.sha256(visible.read_bytes()).hexdigest()
            (instance / "instance.yaml").write_text(
                "\n".join(
                    (
                        "schema_version: 1",
                        "instance_id: pyvisa_dut_validation_v1",
                        "evaluator:",
                        "  id: pyvisa_dut_validation_v1",
                        "  protocol_version: 1",
                        "visible_files:",
                        f"  task.txt: {digest}",
                    )
                )
            )
            (evaluator / "evaluator.yaml").write_text(
                "\n".join(
                    (
                        "schema_version: 1",
                        "evaluator_id: pyvisa_dut_validation_v1",
                        "protocol_version: 1",
                        "supported_instances:",
                        "  - pyvisa_dut_validation_v1",
                    )
                )
            )
            package = evaluator / "instrument_benchmark_evaluator"
            package.mkdir()
            (package / "__init__.py").write_text("")
            (package / "cli.py").write_text(
                "import argparse,json\n"
                "p=argparse.ArgumentParser();s=p.add_subparsers(dest='c');r=s.add_parser('run');"
                "r.add_argument('--request');r.add_argument('--report');a=p.parse_args();"
                "q=json.load(open(a.request));json.dump({'schema_version':1,'status':'completed',"
                "'strict_pass':True,'score':100,'dimensions':{},'strict_gates':{},"
                "'evidence_confidence':{},'worlds':[]},open(a.report,'w'))\n"
            )
            for repo in (instance, evaluator):
                subprocess.run(["git", "add", "."], cwd=repo, check=True)
                subprocess.run(["git", "commit", "-m", "contract"], cwd=repo, check=True)

            config = root / "run.yaml"
            report = root / "report.json"
            config.write_text(
                "\n".join(
                    (
                        "schema_version: 1",
                        "run_id: fake",
                        f"instance_checkout: {instance}",
                        "instance_id: pyvisa_dut_validation_v1",
                        f"evaluator_checkout: {evaluator}",
                        "evaluator_id: pyvisa_dut_validation_v1",
                        f"candidate_path: {candidate}",
                        f"report_path: {report}",
                        "timeout_seconds: 30",
                        "max_output_bytes: 65536",
                        "repeated_worlds: 1",
                        "repeated_base_seed: 40000",
                    )
                )
            )
            result = run_benchmark(
                config,
                instrument_checkout=instrument,
                allow_dirty=False,
            )
            self.assertEqual(result["score"], 100)
            self.assertEqual(
                set(result["provenance"]),
                {"instrument", "instance", "evaluator"},
            )
            self.assertTrue(report.is_file())


if __name__ == "__main__":
    unittest.main()
