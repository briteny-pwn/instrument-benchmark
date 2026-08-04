from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from instrument_benchmark.contracts import (  # noqa: E402
    ContractError,
    validate_evaluator_report,
)


FIXED_WORLD_IDS = (
    "nominal",
    "reordered_resources",
    "distractor_devices",
    "numeric_formats",
    "binary_block_variants",
    "delayed_settle",
    "dirty_initial_state",
    "dut_gain_failure",
    "command_error",
)
WORLD_IDS = FIXED_WORLD_IDS + tuple(
    f"repeated_{index:03d}" for index in range(10)
)


def event(
    sequence: int,
    previous: str,
    kind: str,
    *,
    world_id: str = "nominal",
    fields: dict | None = None,
) -> dict:
    unsigned = {
        "run_id": "run-v2",
        "world_id": world_id,
        "sequence": sequence,
        "monotonic_ns": sequence,
        "previous_hash": previous,
        "kind": kind,
        "fields": fields or {},
    }
    digest = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {**unsigned, "event_hash": digest}


def mount(destination: str, writable: bool) -> dict:
    return {
        "type": "bind",
        "source": "/host" + destination,
        "destination": destination,
        "mode": "rw" if writable else "ro",
        "writable": writable,
    }


def container(role: str) -> dict:
    candidate = role == "candidate"
    value = {
        "container_id": role,
        "image_digest": "sha256:" + ("1" if candidate else "2") * 64,
        "network_mode": "none",
        "readonly_rootfs": True,
        "user": "10001:10001" if candidate else "11001:11001",
        "cap_drop": ["ALL"],
        "security_options": ["no-new-privileges"],
        "mounts": (
            [
                mount("/workspace", False),
                mount("/runner", False),
                mount("/run/iab", False),
            ]
            if candidate
            else [
                mount("/run/iab/transport", True),
                mount("/run/iab/evidence", True),
                mount("/run/iab/world.json", False),
            ]
        ),
        "cleanup_attempted": True,
        "cleanup_succeeded": True,
    }
    if candidate:
        value["candidate_status"] = "completed"
    return value


def journal(world_id: str = "nominal") -> dict:
    first = event(1, "0" * 64, "lifecycle.start", world_id=world_id)
    last = event(
        2, first["event_hash"], "lifecycle.finalized", world_id=world_id
    )
    return {
        "events": [first, last],
        "event_count": 2,
        "final_hash": last["event_hash"],
        "pre_cleanup_snapshot": {"safe": True},
        "post_cleanup_snapshot": {"safe": True},
        "fatal": None,
    }


def v2_world(world_id: str = "nominal") -> dict:
    return {
        "world_id": world_id,
        "status": "completed",
        "errors": [],
        "infrastructure_valid": True,
        "retry_eligible": False,
        "candidate_container_evidence": container("candidate"),
        "sim_container_evidence": container("sim"),
        "sim_journal_evidence": journal(world_id),
    }


def v2_report() -> dict:
    return {
        "schema_version": 2,
        "status": "completed",
        "strict_pass": True,
        "score": 100,
        "dimensions": {},
        "strict_gates": {},
        "evidence_confidence": {},
        "infrastructure_valid": True,
        "retry_eligible": False,
        "worlds": [copy.deepcopy(v2_world(world_id)) for world_id in WORLD_IDS],
        "evaluator": {
            "id": "pyvisa_dut_validation_v2",
            "protocol_version": 1,
            "run_id": "run-v2",
        },
    }


class V2ReportContractTests(unittest.TestCase):
    def test_valid_schema_two_checks_both_siblings_and_journal(self) -> None:
        report = v2_report()
        self.assertIs(
            validate_evaluator_report(report, "pyvisa_dut_validation_v2"),
            report,
        )

    def test_valid_v1_schema_remains_accepted(self) -> None:
        report = {
            "schema_version": 1,
            "status": "completed",
            "strict_pass": True,
            "score": 100,
            "dimensions": {},
            "strict_gates": {},
            "evidence_confidence": {},
            "infrastructure_valid": True,
            "retry_eligible": False,
            "worlds": [{"container_evidence": container("candidate")}],
        }
        self.assertIs(
            validate_evaluator_report(report, "pyvisa_dut_validation_v1"),
            report,
        )

    def test_valid_v2_rejects_security_mount_cleanup_and_journal_drift(self) -> None:
        mutations = {
            "candidate user": lambda w: w["candidate_container_evidence"].update(
                user="0:0"
            ),
            "sim network": lambda w: w["sim_container_evidence"].update(
                network_mode="bridge"
            ),
            "sim root": lambda w: w["sim_container_evidence"].update(
                readonly_rootfs=False
            ),
            "candidate mount": lambda w: w["candidate_container_evidence"][
                "mounts"
            ].append(mount("/secret", False)),
            "sim cleanup": lambda w: w["sim_container_evidence"].update(
                cleanup_succeeded=False
            ),
            "journal count": lambda w: w["sim_journal_evidence"].update(
                event_count=3
            ),
            "journal hash": lambda w: w["sim_journal_evidence"].update(
                final_hash="0" * 64
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                report = v2_report()
                mutate(report["worlds"][0])
                with self.assertRaises(ContractError):
                    validate_evaluator_report(
                        report, "pyvisa_dut_validation_v2"
                    )

    def test_evaluator_id_and_missing_valid_sibling_are_rejected(self) -> None:
        report = v2_report()
        report["evaluator"]["id"] = "pyvisa_dut_validation_v1"
        with self.assertRaisesRegex(ContractError, "evaluator"):
            validate_evaluator_report(report, "pyvisa_dut_validation_v2")

    def test_world_composition_and_current_run_id_are_bound(self) -> None:
        report = v2_report()
        report["worlds"][1] = copy.deepcopy(report["worlds"][0])
        with self.assertRaisesRegex(ContractError, "world|nineteen"):
            validate_evaluator_report(report, "pyvisa_dut_validation_v2")

        report = v2_report()
        with self.assertRaisesRegex(ContractError, "run"):
            validate_evaluator_report(
                report,
                "pyvisa_dut_validation_v2",
                expected_run_id="another-run",
            )

    def test_infrastructure_failure_status_and_fatal_marker_are_bound(self) -> None:
        report = v2_report()
        world = report["worlds"][0]
        world.update(
            infrastructure_valid=False,
            retry_eligible=True,
            errors=["trusted simulator failed"],
            candidate_container_evidence=None,
            sim_container_evidence=None,
            sim_journal_evidence=None,
        )
        report["infrastructure_valid"] = False
        report["retry_eligible"] = True
        with self.assertRaisesRegex(ContractError, "status"):
            validate_evaluator_report(report, "pyvisa_dut_validation_v2")

        world["status"] = "infrastructure_failure"
        fatal_fields = {
            "schema_version": 1,
            "run_id": "run-v2",
            "failure_kind": "trusted_sim_failure",
            "exception_type": "RuntimeError",
            "message": "boom",
        }
        fatal_event = event(
            1,
            "0" * 64,
            "trusted.fatal",
            world_id="nominal",
            fields=fatal_fields,
        )
        world["sim_journal_evidence"] = {
            "events": [fatal_event],
            "event_count": 1,
            "final_hash": fatal_event["event_hash"],
            "pre_cleanup_snapshot": None,
            "post_cleanup_snapshot": None,
            "fatal": {
                **fatal_fields,
                "final_hash": "0" * 64,
            },
        }
        with self.assertRaisesRegex(ContractError, "fatal"):
            validate_evaluator_report(report, "pyvisa_dut_validation_v2")
        world["sim_journal_evidence"]["fatal"]["final_hash"] = fatal_event[
            "event_hash"
        ]
        self.assertIs(
            validate_evaluator_report(report, "pyvisa_dut_validation_v2"),
            report,
        )

        report = v2_report()
        report["worlds"][0]["sim_container_evidence"] = None
        with self.assertRaisesRegex(ContractError, "evidence|infrastructure"):
            validate_evaluator_report(report, "pyvisa_dut_validation_v2")

    def test_retryable_trusted_failure_may_omit_sibling_evidence(self) -> None:
        report = v2_report()
        world = report["worlds"][0]
        world.update(
            status="infrastructure_failure",
            infrastructure_valid=False,
            retry_eligible=True,
            errors=["sim readiness failed"],
            candidate_container_evidence=None,
            sim_container_evidence=None,
            sim_journal_evidence=None,
        )
        report["infrastructure_valid"] = False
        report["retry_eligible"] = True
        self.assertIs(
            validate_evaluator_report(report, "pyvisa_dut_validation_v2"),
            report,
        )
        world["errors"] = []
        with self.assertRaisesRegex(ContractError, "trusted|errors"):
            validate_evaluator_report(report, "pyvisa_dut_validation_v2")


if __name__ == "__main__":
    unittest.main()
