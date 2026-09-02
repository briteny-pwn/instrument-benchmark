from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.validate_distributed_benchmark import (
    EXPECTED_IDENTITIES,
    _adversarial_cases,
    _v2_invariants,
    main,
    semantic_projection,
)
from instrument_benchmark.contracts import load_run_config
from instrument_benchmark.environment import (  # noqa: E402
    RepositoryPaths,
    load_repository_paths,
)


ROOT = Path(__file__).resolve().parents[1]


class FormalValidationScriptTests(unittest.TestCase):
    @staticmethod
    def _mounts_report(*mounts: dict[str, object]) -> dict[str, object]:
        return {
            "source_id": "pyvisa",
            "container_evidence": {"mounts": list(mounts)},
        }

    @staticmethod
    def _mount(
        source: str,
        destination: str,
        *,
        mount_type: str = "bind",
        mode: str = "",
        writable: bool = False,
    ) -> dict[str, object]:
        return {
            "type": mount_type,
            "source": source,
            "destination": destination,
            "mode": mode,
            "writable": writable,
        }

    def test_semantic_projection_normalizes_only_ephemeral_mount_sources(self) -> None:
        temporary = Path(tempfile.gettempdir()).resolve()
        first = self._mounts_report(
            self._mount(f"{temporary}/iab-first/w-alpha/workspace", "/workspace"),
            self._mount(f"{temporary}/iab-first/w-alpha/runner", "/runner"),
        )
        second = self._mounts_report(
            self._mount(f"{temporary}/iab-second/w-beta/workspace", "/workspace"),
            self._mount(f"{temporary}/iab-second/w-beta/runner", "/runner"),
        )

        self.assertEqual(semantic_projection(first), semantic_projection(second))
        stable_first = self._mounts_report(
            self._mount("/trusted/runner", "/runner")
        )
        stable_second = self._mounts_report(
            self._mount("/unexpected/runner", "/runner")
        )
        self.assertNotEqual(
            semantic_projection(stable_first), semantic_projection(stable_second)
        )
        self.assertEqual(semantic_projection(first)["source_id"], "pyvisa")

    def test_semantic_projection_normalizes_mount_order_only(self) -> None:
        temporary = Path(tempfile.gettempdir()).resolve()
        workspace = self._mount(
            f"{temporary}/iab-first/w-alpha/workspace", "/workspace"
        )
        runner = self._mount(f"{temporary}/iab-first/w-alpha/runner", "/runner")

        self.assertEqual(
            semantic_projection(self._mounts_report(workspace, runner)),
            semantic_projection(self._mounts_report(runner, workspace)),
        )

    def test_semantic_projection_preserves_mount_security_fields(self) -> None:
        temporary = Path(tempfile.gettempdir()).resolve()
        baseline = self._mount(
            f"{temporary}/iab-first/w-alpha/workspace", "/workspace"
        )
        mutations = {
            "type": "volume",
            "destination": "/unexpected",
            "mode": "z",
            "writable": True,
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                changed = dict(baseline)
                changed[field] = value
                self.assertNotEqual(
                    semantic_projection(self._mounts_report(baseline)),
                    semantic_projection(self._mounts_report(changed)),
                )

    def test_v2_invariants_require_literal_and_complete_sibling_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "solution.py"
            reference.write_text(
                'import pyvisa\nrm = pyvisa.ResourceManager("@iab")\n'
            )
            config = SimpleNamespace(
                source_id="pyvisa",
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
                "schema_version": 3,
                "source_id": "pyvisa",
                "evaluator": {
                    "source_id": "pyvisa",
                    "id": "pyvisa_dut_validation_v2",
                    "protocol_version": 2,
                },
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

    def test_validator_defaults_to_source_grouped_v1_config(self) -> None:
        class StopAfterConfig(RuntimeError):
            pass

        repositories = RepositoryPaths(Path("/instances"), Path("/evaluator"))
        with (
            mock.patch(
                "scripts.validate_distributed_benchmark.load_repository_paths",
                return_value=repositories,
            ) as environment_loader,
            mock.patch(
                "scripts.validate_distributed_benchmark.load_run_config",
                side_effect=StopAfterConfig,
            ) as loader,
        ):
            with self.assertRaises(StopAfterConfig):
                main([])

        environment_loader.assert_called_once_with(ROOT)
        loader.assert_called_once_with(
            (ROOT / "configs/pyvisa/pyvisa_dut_validation_v1.yaml").resolve(),
            repositories,
        )

    def test_source_grouped_pyvisa_configs_bind_exact_report_versions(self) -> None:
        cases = (
            ("pyvisa_dut_validation_v1", 2),
            ("pyvisa_dut_validation_v2", 3),
        )
        repositories = load_repository_paths(ROOT)
        for evaluator_id, report_version in cases:
            with self.subTest(evaluator_id=evaluator_id):
                config = load_run_config(
                    ROOT / "configs" / "pyvisa" / f"{evaluator_id}.yaml",
                    repositories,
                )
                self.assertEqual(config.source_id, "pyvisa")
                self.assertEqual(config.evaluator_id, evaluator_id)
                self.assertEqual(
                    EXPECTED_IDENTITIES[(config.source_id, config.evaluator_id)],
                    report_version,
                )

    def test_validator_rejects_cross_source_evaluator_identity(self) -> None:
        config = SimpleNamespace(
            source_id="openfibsem",
            evaluator_id="pyvisa_dut_validation_v1",
            instances_repo_path=ROOT.parent / "instance",
        )
        repositories = RepositoryPaths(Path("/instances"), Path("/evaluator"))
        with (
            mock.patch(
                "scripts.validate_distributed_benchmark.load_repository_paths",
                return_value=repositories,
            ),
            mock.patch(
                "scripts.validate_distributed_benchmark.load_run_config",
                return_value=config,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "source.*evaluator|identity"):
                main([])

    def test_v2_adversarial_contract_keeps_protocol_and_leak_cases(self) -> None:
        cases = _adversarial_cases(
            Path("/unused"), "pyvisa", "pyvisa_dut_validation_v2"
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
