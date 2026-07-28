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
    validate_evaluator_report,
    validate_evaluator_container_evidence,
)
from instrument_benchmark.orchestrator import run_benchmark  # noqa: E402
from instrument_benchmark.evaluator_image import EvaluatorImageEvidence  # noqa: E402
from instrument_benchmark.evaluator_runtime import (  # noqa: E402
    EvaluatorContainerEvidence,
    EvaluatorContainerResult,
)
from scripts.validate_distributed_benchmark import semantic_projection  # noqa: E402


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
            "container": {"protocol_version": 1},
        }
        evaluator = {
            "evaluator_id": "pyvisa_dut_validation_v1",
            "protocol_version": 1,
            "supported_instances": ["pyvisa_dut_validation_v1"],
            "container_protocol_version": 1,
            "candidate_execution": "docker",
            "image_mode": "locked",
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
                        "container_protocol_version: 1",
                        "image_mode: locked",
                    )
                )
            )
            loaded = load_run_config(config)
            self.assertEqual(loaded.instance_checkout, (root / "instance").resolve())
            self.assertEqual(loaded.report_path, (root / "report.json").resolve())

    def test_fake_evaluator_is_invoked_through_outer_container_runner(self) -> None:
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
                        "container:",
                        "  protocol_version: 1",
                        "  lock_file: image.lock.yaml",
                    )
                )
            )
            (instance / "image.lock.yaml").write_text(
                "dockerfile_sha256: " + "1" * 64 + "\n"
                "built_image:\n"
                "  digest: sha256:" + "2" * 64 + "\n"
            )
            (evaluator / "evaluator.yaml").write_text(
                "\n".join(
                    (
                        "schema_version: 1",
                        "evaluator_id: pyvisa_dut_validation_v1",
                        "protocol_version: 1",
                        "container_protocol_version: 1",
                        "candidate_execution: docker",
                        "image_mode: locked",
                        "supported_instances:",
                        "  - pyvisa_dut_validation_v1",
                    )
                )
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
                        "container_protocol_version: 1",
                        "image_mode: locked",
                    )
                )
            )
            image = EvaluatorImageEvidence(
                reference="iab/evaluator:test",
                image_id="sha256:" + "a" * 64,
                repo_digest=None,
                dockerfile_sha256="b" * 64,
                build_manifest_sha256="c" * 64,
                evaluator_commit="d" * 40,
                platform="linux/amd64",
                user="11001:11001",
            )
            outer = EvaluatorContainerEvidence(
                container_id="outer",
                image_id=image.image_id,
                image_reference=image.reference,
                dockerfile_sha256=image.dockerfile_sha256,
                build_manifest_sha256=image.build_manifest_sha256,
                evaluator_commit=image.evaluator_commit,
                created_at="created",
                started_at="started",
                finished_at="finished",
                exit_code=0,
                oom_killed=False,
                network_mode="none",
                readonly_rootfs=True,
                user="11001:11001",
                group_add=("999",),
                cap_drop=("ALL",),
                security_options=("no-new-privileges",),
                pids_limit=256,
                memory_bytes=2 * 1024**3,
                memory_swap_bytes=2 * 1024**3,
                nano_cpus=2_000_000_000,
                mounts=(
                    {
                        "Source": "/host/docker.sock",
                        "Destination": "/var/run/docker.sock",
                        "RW": True,
                    },
                ),
                stdout_bytes=0,
                stderr_bytes=0,
                stdout_sha256="e" * 64,
                stderr_sha256="f" * 64,
                report_sha256="1" * 64,
                cleanup_succeeded=True,
            )
            evaluator_report = {
                "schema_version": 1,
                "status": "completed",
                "strict_pass": True,
                "score": 100,
                "dimensions": {},
                "strict_gates": {},
                "evidence_confidence": {},
                "infrastructure_valid": True,
                "retry_eligible": False,
                "worlds": [
                    {
                        "container_evidence": {
                            "container_id": "candidate",
                            "image_digest": "sha256:" + "2" * 64,
                            "network_mode": "none",
                            "readonly_rootfs": True,
                            "user": "10001:10001",
                            "cleanup_succeeded": True,
                        }
                    }
                ],
            }

            class FakeBuilder:
                def build(self, checkout, *, run_id):
                    self.checkout = checkout
                    self.run_id = run_id
                    return image

            class FakeRunner:
                def run(self, **kwargs):
                    request_value = json.loads(kwargs["request_path"].read_text())
                    assert kwargs["shared_run_root"] == kwargs[
                        "shared_run_root"
                    ].resolve()
                    assert request_value["shared_run_root"] == str(
                        kwargs["shared_run_root"]
                    )
                    kwargs["report_path"].write_text(json.dumps(evaluator_report))
                    return EvaluatorContainerResult(
                        report=evaluator_report,
                        evidence=outer,
                        stdout="",
                        stderr="",
                    )

            result = run_benchmark(
                config,
                instrument_checkout=instrument,
                allow_dirty=False,
                image_builder_factory=FakeBuilder,
                runner_factory=FakeRunner,
            )
            self.assertEqual(result["score"], 100)
            self.assertEqual(
                set(result["provenance"]),
                {"instrument", "instance", "evaluator"},
            )
            self.assertTrue(report.is_file())
            self.assertEqual(
                result["orchestration"]["evaluator_container"]["container_id"],
                "outer",
            )
            self.assertEqual(
                result["worlds"][0]["container_evidence"]["container_id"],
                "candidate",
            )

    def test_report_requires_per_world_docker_security_evidence(self) -> None:
        base = {
            "schema_version": 1,
            "status": "completed",
            "strict_pass": True,
            "score": 100,
            "dimensions": {},
            "strict_gates": {},
            "evidence_confidence": {},
            "infrastructure_valid": True,
            "retry_eligible": False,
            "worlds": [{"container_evidence": None}],
        }
        with self.assertRaisesRegex(ContractError, "container evidence"):
            validate_evaluator_report(base)
        base["worlds"][0]["container_evidence"] = {
            "container_id": "c1",
            "image_digest": "",
            "network_mode": "none",
            "readonly_rootfs": True,
            "user": "10001:10001",
            "cleanup_succeeded": True,
        }
        with self.assertRaisesRegex(ContractError, "image digest"):
            validate_evaluator_report(base)

    def test_outer_evidence_requires_hardened_runtime_and_socket_mount(self) -> None:
        evidence = {
            "container_id": "outer",
            "image_id": "sha256:" + "a" * 64,
            "dockerfile_sha256": "b" * 64,
            "build_manifest_sha256": "c" * 64,
            "network_mode": "none",
            "readonly_rootfs": True,
            "user": "11001:11001",
            "cap_drop": ["ALL"],
            "security_options": ["no-new-privileges"],
            "mounts": [
                {
                    "Source": "/host/docker.sock",
                    "Destination": "/var/run/docker.sock",
                }
            ],
            "cleanup_succeeded": True,
        }
        self.assertIs(validate_evaluator_container_evidence(evidence), evidence)
        evidence["network_mode"] = "bridge"
        with self.assertRaisesRegex(ContractError, "security"):
            validate_evaluator_container_evidence(evidence)
    def test_semantic_projection_ignores_run_provenance(self) -> None:
        first = {
            "score": 100,
            "worlds": [{
                "constraints": [{"evidence_sequences": [1, 2]}],
                "container_evidence": {
                    "container_id": "first",
                    "created_at": "time-1",
                    "cleanup_succeeded": True,
                },
            }],
            "provenance": {"instrument": {"dirty": False}},
            "orchestration": {"evaluator_exit_code": 0},
        }
        second = {
            "score": 100,
            "worlds": [{
                "constraints": [{"evidence_sequences": [99, 100]}],
                "container_evidence": {
                    "container_id": "second",
                    "created_at": "time-2",
                    "cleanup_succeeded": True,
                },
            }],
            "provenance": {"instrument": {"dirty": True}},
            "orchestration": {"evaluator_exit_code": 0},
        }
        self.assertEqual(
            semantic_projection(first),
            semantic_projection(second),
        )


if __name__ == "__main__":
    unittest.main()
