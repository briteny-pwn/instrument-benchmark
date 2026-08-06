from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from instrument_benchmark.contracts import (  # noqa: E402
    ContractError,
    RunConfig,
    dump_json,
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
    def write_source_registry(
        self, checkout: Path, source_id: str, key: str, leaf_ids: list[str]
    ) -> Path:
        source = checkout / "sources" / source_id
        source.mkdir(parents=True, exist_ok=True)
        source.joinpath("source.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "source_id": source_id,
                    "display_name": source_id,
                    "description": f"{source_id} fixtures",
                    key: sorted(leaf_ids),
                },
                sort_keys=False,
            )
        )
        return source

    def write_instance_leaf(
        self, checkout: Path, source_id: str, instance_id: str
    ) -> Path:
        source = self.write_source_registry(
            checkout, source_id, "instances", [instance_id]
        )
        leaf = source / instance_id
        leaf.mkdir()
        visible = leaf / "task.txt"
        visible.write_text("visible")
        digest = hashlib.sha256(visible.read_bytes()).hexdigest()
        leaf.joinpath("instance.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 2,
                    "source_id": source_id,
                    "instance_id": instance_id,
                    "evaluator": {"id": instance_id, "protocol_version": 2},
                    "visible_files": {"task.txt": digest},
                    "container": {
                        "protocol_version": 1,
                        "lock_file": "image.lock.yaml",
                    },
                },
                sort_keys=False,
            )
        )
        leaf.joinpath("image.lock.yaml").write_text(
            "dockerfile_sha256: " + "1" * 64 + "\n"
            "built_image:\n"
            "  digest: sha256:" + "2" * 64 + "\n"
        )
        return leaf

    def write_evaluator_leaf(
        self, checkout: Path, source_id: str, evaluator_id: str
    ) -> Path:
        source = self.write_source_registry(
            checkout, source_id, "evaluators", [evaluator_id]
        )
        leaf = source / evaluator_id
        leaf.mkdir()
        leaf.joinpath("evaluator.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 2,
                    "source_id": source_id,
                    "evaluator_id": evaluator_id,
                    "protocol_version": 2,
                    "container_protocol_version": 1,
                    "candidate_execution": "docker",
                    "image_mode": "locked",
                    "supported_instances": [evaluator_id],
                    "fixed_worlds": ["nominal"],
                },
                sort_keys=False,
            )
        )
        return leaf

    def test_run_config_requires_schema_v2_and_source_id_before_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("instance", "evaluator"):
                (root / name).mkdir()
            (root / "solution.py").write_text("pass\n")
            base = {
                "schema_version": 2,
                "run_id": "run",
                "source_id": "pyvisa",
                "instance_checkout": "instance",
                "instance_id": "pyvisa_dut_validation_v1",
                "evaluator_checkout": "evaluator",
                "evaluator_id": "pyvisa_dut_validation_v1",
                "candidate_path": "solution.py",
                "report_path": "report.json",
                "timeout_seconds": 30,
                "max_output_bytes": 65536,
                "repeated_worlds": 10,
                "repeated_base_seed": 40000,
                "container_protocol_version": 1,
                "image_mode": "locked",
            }
            config = root / "run.yaml"

            for mutate in (
                lambda value: value.update(schema_version=1),
                lambda value: value.pop("source_id"),
                lambda value: value.update(unknown_field=True),
            ):
                value = dict(base)
                mutate(value)
                config.write_text(yaml.safe_dump(value))
                with (
                    patch("instrument_benchmark.contracts._git") as git,
                    patch("instrument_benchmark.contracts.subprocess.run") as process,
                ):
                    with self.assertRaises(ContractError):
                        load_run_config(config)
                git.assert_not_called()
                process.assert_not_called()

    def test_run_config_v2_validates_all_composite_identity_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("instance", "evaluator"):
                (root / name).mkdir()
            (root / "solution.py").write_text("pass\n")
            base = {
                "schema_version": 2,
                "run_id": "run",
                "source_id": "pyvisa",
                "instance_checkout": "instance",
                "instance_id": "pyvisa_dut_validation_v1",
                "evaluator_checkout": "evaluator",
                "evaluator_id": "pyvisa_dut_validation_v1",
                "candidate_path": "solution.py",
                "report_path": "report.json",
                "timeout_seconds": 30,
                "max_output_bytes": 65536,
                "repeated_worlds": 10,
                "repeated_base_seed": 40000,
                "container_protocol_version": 1,
                "image_mode": "locked",
            }
            config = root / "run.yaml"
            for field in ("source_id", "instance_id", "evaluator_id"):
                value = dict(base)
                value[field] = "../escape"
                config.write_text(yaml.safe_dump(value))
                with self.assertRaisesRegex(ContractError, "invalid"):
                    load_run_config(config)

            config.write_text(yaml.safe_dump(base))
            loaded = load_run_config(config)
            self.assertEqual(loaded.schema_version, 2)
            self.assertEqual(loaded.source_id, "pyvisa")

    def test_run_json_schema_v2_uses_composite_fibsem_identity(self) -> None:
        schema = json.loads((ROOT / "schemas" / "run.schema.json").read_text())
        properties = schema["properties"]

        self.assertEqual(properties["schema_version"], {"const": 2})
        self.assertIn("source_id", schema["required"])
        for field in ("source_id", "instance_id", "evaluator_id"):
            self.assertEqual(
                properties[field]["pattern"], "^[a-z][a-z0-9_-]*$"
            )
        condition = schema["allOf"][0]
        self.assertEqual(
            condition["if"]["properties"],
            {
                "source_id": {"const": "openfibsem"},
                "evaluator_id": {"const": "fibsem_liftout_v1"},
            },
        )
        self.assertEqual(
            set(condition["then"]["required"]),
            {"openfibsem_checkout", "openfibsem_commit"},
        )

    def test_configs_and_tracked_report_are_grouped_by_source(self) -> None:
        self.assertEqual(list((ROOT / "configs").glob("*.yaml")), [])
        expected = {
            "pyvisa/pyvisa_dut_validation_v1.yaml": (
                "pyvisa",
                "../../../evaluator/sources/pyvisa/pyvisa_dut_validation_v1/reference/solution.py",
                "../../reports/pyvisa/pyvisa_dut_validation_v1.json",
            ),
            "pyvisa/pyvisa_dut_validation_v2.yaml": (
                "pyvisa",
                "../../../evaluator/sources/pyvisa/pyvisa_dut_validation_v2/reference/solution.py",
                "../../reports/pyvisa/pyvisa_dut_validation_v2.json",
            ),
            "openfibsem/fibsem_liftout_v1.yaml": (
                "openfibsem",
                "../../../evaluator/sources/openfibsem/fibsem_liftout_v1/reference/solution.py",
                "../../reports/openfibsem/fibsem_liftout_v1.json",
            ),
        }
        for relative, values in expected.items():
            with self.subTest(config=relative):
                value = yaml.safe_load((ROOT / "configs" / relative).read_text())
                self.assertEqual(value["schema_version"], 2)
                self.assertEqual(
                    (
                        value["source_id"],
                        value["candidate_path"],
                        value["report_path"],
                    ),
                    values,
                )
                self.assertEqual(value["instance_checkout"], "../../../instance")
                self.assertEqual(value["evaluator_checkout"], "../../../evaluator")
        self.assertTrue(
            (ROOT / "reports/pyvisa/pyvisa_dut_validation_v1.json").is_file()
        )
        self.assertFalse((ROOT / "reports/distributed_validation.json").exists())

    def test_v2_request_is_bound_to_composite_identity_and_image_id(
        self,
    ) -> None:
        from instrument_benchmark.orchestrator import _build_evaluator_request

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evaluator = root / "evaluator"
            evaluator.mkdir()
            candidate = root / "solution.py"
            candidate.write_text("pass\n")

            common = dict(
                schema_version=2,
                run_id="run",
                source_id="pyvisa",
                instance_checkout=root,
                instance_id="pyvisa_dut_validation_v1",
                evaluator_checkout=evaluator,
                evaluator_id="pyvisa_dut_validation_v1",
                candidate_path=candidate,
                report_path=root / "report.json",
                timeout_seconds=30.0,
                max_output_bytes=65536,
                repeated_worlds=10,
                repeated_base_seed=40000,
                container_protocol_version=1,
                image_mode="locked",
            )
            config = RunConfig(**common)
            manifest = {"protocol_version": 2}
            request = _build_evaluator_request(
                config,
                instance_root=root,
                shared_run_root=root,
                evaluator_manifest=manifest,
                evaluator_image_id="sha256:" + "a" * 64,
            )
            self.assertEqual(request["protocol_version"], 2)
            self.assertEqual(request["source_id"], "pyvisa")
            self.assertEqual(request["instance_id"], "pyvisa_dut_validation_v1")
            self.assertEqual(request["evaluator_id"], "pyvisa_dut_validation_v1")
            self.assertNotIn("evaluator_image_id", request)

            common.update(
                instance_id="pyvisa_dut_validation_v2",
                evaluator_id="pyvisa_dut_validation_v2",
            )
            request = _build_evaluator_request(
                RunConfig(**common),
                instance_root=root,
                shared_run_root=root,
                evaluator_manifest=manifest,
                evaluator_image_id="sha256:" + "b" * 64,
            )
            self.assertEqual(
                request["evaluator_image_id"], "sha256:" + "b" * 64
            )

            common.update(
                instance_id="fibsem_liftout_v1",
                evaluator_id="fibsem_liftout_v1",
            )
            request = _build_evaluator_request(
                RunConfig(**common),
                instance_root=root,
                shared_run_root=root,
                evaluator_manifest=manifest,
                evaluator_image_id="sha256:" + "c" * 64,
            )
            self.assertNotIn("evaluator_image_id", request)

    def test_dump_json_creates_nested_report_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "reports" / "openfibsem" / "run.json"
            real_replace = __import__("os").replace
            moves: list[tuple[Path, Path]] = []

            def record_replace(source, destination):
                moves.append((Path(source), Path(destination)))
                real_replace(source, destination)

            with patch("instrument_benchmark.contracts.os.replace", record_replace):
                dump_json(report, {"ok": True})

            self.assertEqual(json.loads(report.read_text()), {"ok": True})
            self.assertEqual(len(moves), 1)
            temporary, destination = moves[0]
            self.assertEqual(destination, report)
            self.assertEqual(temporary.parent, report.parent)
            self.assertTrue(temporary.name.endswith(".tmp"))
            self.assertEqual(list(report.parent.glob("*.tmp")), [])

    def test_dump_json_cleans_temporary_file_when_fsync_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "reports" / "openfibsem" / "run.json"
            report.parent.mkdir(parents=True)
            report.write_text('{"original": true}\n')

            failure = OSError("forced fsync failure")
            with patch(
                "instrument_benchmark.contracts.os.fsync", side_effect=failure
            ):
                with self.assertRaises(OSError) as raised:
                    dump_json(report, {"replacement": True})

            self.assertIs(raised.exception, failure)
            self.assertEqual(report.read_text(), '{"original": true}\n')
            self.assertEqual(list(report.parent.glob("*.tmp")), [])

    def test_v2_run_forwards_the_builder_image_id_to_the_evaluator(self) -> None:
        from tests.test_v2_contracts import v2_report

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instrument = root / "instrument"
            instance = root / "instance"
            evaluator = root / "evaluator"
            for path in (instrument, instance, evaluator):
                path.mkdir()
            candidate = root / "solution.py"
            candidate.write_text("pass\n")
            self.write_instance_leaf(
                instance, "pyvisa", "pyvisa_dut_validation_v2"
            )
            self.write_evaluator_leaf(
                evaluator, "pyvisa", "pyvisa_dut_validation_v2"
            )
            report_path = root / "report.json"
            config = root / "run.yaml"
            config.write_text(
                "\n".join(
                    (
                        "schema_version: 2",
                        "run_id: run-v2",
                        "source_id: pyvisa",
                        f"instance_checkout: {instance}",
                        "instance_id: pyvisa_dut_validation_v2",
                        f"evaluator_checkout: {evaluator}",
                        "evaluator_id: pyvisa_dut_validation_v2",
                        f"candidate_path: {candidate}",
                        f"report_path: {report_path}",
                        "timeout_seconds: 30",
                        "max_output_bytes: 65536",
                        "repeated_worlds: 10",
                        "repeated_base_seed: 40000",
                        "container_protocol_version: 1",
                        "image_mode: locked",
                    )
                )
            )
            image_id = "sha256:" + "a" * 64
            image = SimpleNamespace(
                reference="iab/evaluator:test",
                image_id=image_id,
                repo_digest="iab/evaluator@" + image_id,
                dockerfile_sha256="b" * 64,
                build_manifest_sha256="c" * 64,
                evaluator_commit="d" * 40,
                source_id="pyvisa",
                evaluator_id="pyvisa_dut_validation_v2",
                source_manifest_sha256="e" * 64,
                source_tree_sha256="f" * 64,
            )
            outer = SimpleNamespace(
                exit_code=0,
                to_dict=lambda: {
                    "container_id": "outer",
                    "image_id": image_id,
                    "dockerfile_sha256": "b" * 64,
                    "build_manifest_sha256": "c" * 64,
                    "network_mode": "none",
                    "readonly_rootfs": True,
                    "user": "11001:11001",
                    "cap_drop": ["ALL"],
                    "security_options": ["no-new-privileges"],
                    "mounts": [
                        {"Destination": "/var/run/docker.sock"}
                    ],
                    "cleanup_succeeded": True,
                },
            )
            seen: dict = {}
            built: dict = {}

            class FakeBuilder:
                def build(self, checkout, *, run_id, source_id, evaluator_id):
                    built.update(
                        source_id=source_id,
                        evaluator_id=evaluator_id,
                    )
                    return image

            class FakeRunner:
                def run(self, **kwargs):
                    seen.update(json.loads(kwargs["request_path"].read_text()))
                    return SimpleNamespace(
                        report=v2_report(), evidence=outer
                    )

            provenance = SimpleNamespace(
                to_dict=lambda: {
                    "path": "fixture",
                    "commit": "e" * 40,
                    "branch": "main",
                    "remote": None,
                    "dirty": False,
                }
            )
            with (
                patch(
                    "instrument_benchmark.orchestrator.repository_provenance",
                    return_value=provenance,
                ),
                patch(
                    "instrument_benchmark.orchestrator._container_provenance",
                    return_value={
                        "image_digest": "sha256:" + "f" * 64,
                        "docker_engine_version": "fixture",
                    },
                ),
            ):
                result = run_benchmark(
                    config,
                    instrument_checkout=instrument,
                    image_builder_factory=FakeBuilder,
                    runner_factory=FakeRunner,
                )

            self.assertEqual(seen["evaluator_image_id"], image_id)
            self.assertEqual(seen["protocol_version"], 2)
            self.assertEqual(seen["source_id"], "pyvisa")
            self.assertEqual(seen["instance_id"], "pyvisa_dut_validation_v2")
            self.assertEqual(seen["evaluator_id"], "pyvisa_dut_validation_v2")
            self.assertEqual(
                built,
                {
                    "source_id": "pyvisa",
                    "evaluator_id": "pyvisa_dut_validation_v2",
                },
            )
            self.assertEqual(
                result["orchestration"]["evaluator_image"]["image_id"],
                image_id,
            )
            self.assertEqual(result["source_id"], "pyvisa")
            self.assertEqual(result["instance_id"], "pyvisa_dut_validation_v2")
            self.assertEqual(result["evaluator_id"], "pyvisa_dut_validation_v2")
            self.assertEqual(
                result["orchestration"]["evaluator_image"]["source_tree_sha256"],
                "f" * 64,
            )

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
            "source_id": "pyvisa",
            "instance_id": "pyvisa_dut_validation_v1",
            "evaluator": {
                "id": "pyvisa_dut_validation_v1",
                "protocol_version": 2,
            },
            "container": {"protocol_version": 1},
        }
        evaluator = {
            "source_id": "pyvisa",
            "evaluator_id": "pyvisa_dut_validation_v1",
            "protocol_version": 2,
            "supported_instances": ["pyvisa_dut_validation_v1"],
            "container_protocol_version": 1,
            "candidate_execution": "docker",
            "image_mode": "locked",
        }
        validate_dependencies("pyvisa", instance, evaluator)
        instance["source_id"] = "other"
        with self.assertRaisesRegex(ContractError, "instance source_id mismatch"):
            validate_dependencies("pyvisa", instance, evaluator)
        instance["source_id"] = "pyvisa"
        evaluator["source_id"] = "other"
        with self.assertRaisesRegex(ContractError, "evaluator source_id mismatch"):
            validate_dependencies("pyvisa", instance, evaluator)
        evaluator["source_id"] = "pyvisa"
        evaluator["protocol_version"] = 1
        with self.assertRaisesRegex(ContractError, "protocol"):
            validate_dependencies("pyvisa", instance, evaluator)

        evaluator["protocol_version"] = 2
        instance["evaluator"]["protocol_version"] = 1
        with self.assertRaisesRegex(ContractError, "protocol"):
            validate_dependencies("pyvisa", instance, evaluator)

        evaluator["protocol_version"] = 1
        with self.assertRaisesRegex(ContractError, "protocol"):
            validate_dependencies("pyvisa", instance, evaluator)

        instance["evaluator"]["protocol_version"] = 2
        evaluator["protocol_version"] = 2
        instance["container"]["protocol_version"] = 2
        evaluator["container_protocol_version"] = 2
        with self.assertRaisesRegex(ContractError, "container protocol"):
            validate_dependencies("pyvisa", instance, evaluator)

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
                        "schema_version: 2",
                        "run_id: test",
                        "source_id: pyvisa",
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

            config.write_text(
                config.read_text().replace(
                    "container_protocol_version: 1",
                    "container_protocol_version: 2",
                )
            )
            with self.assertRaisesRegex(ContractError, "container_protocol_version"):
                load_run_config(config)

    def test_fake_evaluator_is_invoked_through_outer_container_runner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instrument = self.make_repo(root, "instrument")
            instance = self.make_repo(root, "instance")
            evaluator = self.make_repo(root, "evaluator")
            candidate = root / "solution.py"
            candidate.write_text("pass")

            self.write_instance_leaf(
                instance, "pyvisa", "pyvisa_dut_validation_v1"
            )
            self.write_evaluator_leaf(
                evaluator, "pyvisa", "pyvisa_dut_validation_v1"
            )
            for repo in (instance, evaluator):
                subprocess.run(["git", "add", "."], cwd=repo, check=True)
                subprocess.run(["git", "commit", "-m", "contract"], cwd=repo, check=True)

            config = root / "run.yaml"
            report = root / "report.json"
            config.write_text(
                "\n".join(
                    (
                        "schema_version: 2",
                        "run_id: fake",
                        "source_id: pyvisa",
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
                source_id="pyvisa",
                evaluator_id="pyvisa_dut_validation_v1",
                source_manifest_sha256="e" * 64,
                source_tree_sha256="f" * 64,
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
                "schema_version": 2,
                "source_id": "pyvisa",
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
                "evaluator": {
                    "source_id": "pyvisa",
                    "id": "pyvisa_dut_validation_v1",
                    "protocol_version": 2,
                    "run_id": "fake",
                },
            }

            class FakeBuilder:
                seen = {}

                def build(self, checkout, *, run_id, source_id, evaluator_id):
                    self.checkout = checkout
                    self.run_id = run_id
                    self.seen = {
                        "source_id": source_id,
                        "evaluator_id": evaluator_id,
                    }
                    return image

            class FakeRunner:
                def run(self, **kwargs):
                    request_value = json.loads(kwargs["request_path"].read_text())
                    assert request_value["protocol_version"] == 2
                    assert request_value["source_id"] == "pyvisa"
                    assert request_value["instance_id"] == "pyvisa_dut_validation_v1"
                    assert request_value["evaluator_id"] == "pyvisa_dut_validation_v1"
                    assert "evaluator_image_id" not in request_value
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

            builder = FakeBuilder()
            result = run_benchmark(
                config,
                instrument_checkout=instrument,
                allow_dirty=False,
                image_builder_factory=lambda: builder,
                runner_factory=FakeRunner,
            )
            self.assertEqual(
                builder.seen,
                {
                    "source_id": "pyvisa",
                    "evaluator_id": "pyvisa_dut_validation_v1",
                },
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
                result["orchestration"]["evaluator_image"]["image_id"],
                image.image_id,
            )
            self.assertEqual(
                result["worlds"][0]["container_evidence"]["container_id"],
                "candidate",
            )

    def test_source_resolution_fails_before_builder_or_runner(self) -> None:
        cases = ("cross_source", "missing_source_manifest", "flat_root")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                instrument = root / "instrument"
                instance = root / "instance"
                evaluator = root / "evaluator"
                for path in (instrument, instance, evaluator):
                    path.mkdir()
                candidate = root / "solution.py"
                candidate.write_text("pass\n")
                if case == "flat_root":
                    self.write_instance_leaf(
                        instance, "pyvisa", "pyvisa_dut_validation_v1"
                    )
                    self.write_evaluator_leaf(
                        evaluator, "pyvisa", "pyvisa_dut_validation_v1"
                    )
                    instance.joinpath("instance.yaml").write_text(
                        "schema_version: 2\nsource_id: pyvisa\n"
                        "instance_id: pyvisa_dut_validation_v1\n"
                    )
                    evaluator.joinpath("evaluator.yaml").write_text(
                        "schema_version: 2\nsource_id: pyvisa\n"
                        "evaluator_id: pyvisa_dut_validation_v1\n"
                    )
                else:
                    self.write_instance_leaf(
                        instance, "pyvisa", "pyvisa_dut_validation_v1"
                    )
                    evaluator_source = "openfibsem" if case == "cross_source" else "pyvisa"
                    source_leaf = self.write_evaluator_leaf(
                        evaluator, evaluator_source, "pyvisa_dut_validation_v1"
                    )
                    if case == "cross_source":
                        manual_leaf = self.write_evaluator_leaf(
                            evaluator, "pyvisa", "pyvisa_dut_validation_v1"
                        )
                        manual_leaf.joinpath("evaluator.yaml").write_text(
                            source_leaf.joinpath("evaluator.yaml").read_text()
                        )
                    if case == "missing_source_manifest":
                        evaluator.joinpath("sources/pyvisa/source.yaml").unlink()
                config = root / "run.yaml"
                config.write_text(
                    yaml.safe_dump(
                        {
                            "schema_version": 2,
                            "run_id": "source-guard",
                            "source_id": "pyvisa",
                            "instance_checkout": str(instance),
                            "instance_id": "pyvisa_dut_validation_v1",
                            "evaluator_checkout": str(evaluator),
                            "evaluator_id": "pyvisa_dut_validation_v1",
                            "candidate_path": str(candidate),
                            "report_path": str(root / "report.json"),
                            "timeout_seconds": 30,
                            "max_output_bytes": 65536,
                            "repeated_worlds": 1,
                            "repeated_base_seed": 40000,
                            "container_protocol_version": 1,
                            "image_mode": "locked",
                        },
                        sort_keys=False,
                    )
                )
                calls = {"builder": 0, "runner": 0}

                def builder_factory():
                    calls["builder"] += 1
                    return object()

                def runner_factory():
                    calls["runner"] += 1
                    return object()

                with patch(
                    "instrument_benchmark.orchestrator.repository_provenance",
                    return_value=SimpleNamespace(to_dict=lambda: {}),
                ):
                    with self.assertRaises(ContractError):
                        run_benchmark(
                            config,
                            instrument_checkout=instrument,
                            image_builder_factory=builder_factory,
                            runner_factory=runner_factory,
                        )
                self.assertEqual(calls, {"builder": 0, "runner": 0})

    def test_report_requires_per_world_docker_security_evidence(self) -> None:
        base = {
            "schema_version": 2,
            "source_id": "pyvisa",
            "status": "completed",
            "strict_pass": True,
            "score": 100,
            "dimensions": {},
            "strict_gates": {},
            "evidence_confidence": {},
            "infrastructure_valid": True,
            "retry_eligible": False,
            "worlds": [{"container_evidence": None}],
            "evaluator": {
                "source_id": "pyvisa",
                "id": "pyvisa_dut_validation_v1",
                "protocol_version": 2,
                "run_id": "run",
            },
        }
        with self.assertRaisesRegex(ContractError, "container evidence"):
            validate_evaluator_report(
                base, "pyvisa", "pyvisa_dut_validation_v1"
            )
        base["worlds"][0]["container_evidence"] = {
            "container_id": "c1",
            "image_digest": "",
            "network_mode": "none",
            "readonly_rootfs": True,
            "user": "10001:10001",
            "cleanup_succeeded": True,
        }
        with self.assertRaisesRegex(ContractError, "image digest"):
            validate_evaluator_report(
                base, "pyvisa", "pyvisa_dut_validation_v1"
            )

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
