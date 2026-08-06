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
COUNTS = {
    "connections_opened": 1,
    "connections_closed": 1,
    "connections_rejected": 0,
    "rpc_requests": 4,
    "rpc_results": 4,
    "rpc_rejections": 0,
    "resource_queries": 0,
    "resource_query_results": 0,
    "resource_query_rejections": 0,
    "sessions_opened": 1,
    "sessions_explicitly_closed": 1,
    "sessions_forced_closed": 0,
    "session_invalid_accesses": 0,
    "scpi_writes": 1,
    "scpi_write_results": 1,
    "scpi_reads": 1,
    "scpi_read_results": 1,
}


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
    snapshot = {
        "clock_ms": 0,
        "closed_routes": [],
        "psu_voltage_v": 0.0,
        "psu_output": False,
        "awg_waveform_name": None,
        "awg_points": [],
        "awg_amplitude_vpp": 1.0,
        "awg_output": False,
        "stimulus_started_ms": None,
        "safe": True,
    }
    broker = {"connections": 1, "leaked_sessions": 0, "frozen": True}
    safe_state = {
        "psu": {"output": False},
        "awg": {"output": False},
        "switch": {"closed_routes": []},
    }
    terminal = {
        "broker": broker,
        "counts": COUNTS,
        "open_sessions": 0,
        "leaked_sessions": 0,
        "safe": True,
        "fatal": None,
    }
    definitions = (
        ("lifecycle.start", {}),
        (
            "lifecycle.configuration",
            {"world_sha256": "1" * 64, "simulator_sha256": "2" * 64},
        ),
        ("lifecycle.socket_bound", {"endpoint_name": "visa.sock", "mode": "0666"}),
        ("broker.ready", {"endpoint_name": "visa.sock"}),
        ("connection.open", {}),
        (
            "rpc.request",
            {"connection_id": "c", "operation": "open_default_resource_manager"},
        ),
        ("session.open", {}),
        (
            "rpc.result",
            {"connection_id": "c", "operation": "open_default_resource_manager"},
        ),
        ("rpc.request", {"connection_id": "c", "operation": "write"}),
        ("scpi.write", {"connection_id": "c"}),
        ("scpi.write_result", {"connection_id": "c"}),
        ("rpc.result", {"connection_id": "c", "operation": "write"}),
        ("rpc.request", {"connection_id": "c", "operation": "read"}),
        ("scpi.read", {"connection_id": "c"}),
        ("scpi.read_result", {"connection_id": "c"}),
        ("rpc.result", {"connection_id": "c", "operation": "read"}),
        ("rpc.request", {"connection_id": "c", "operation": "close"}),
        ("session.close", {}),
        ("rpc.result", {"connection_id": "c", "operation": "close"}),
        ("connection.close", {}),
        ("lifecycle.signal", {"signal": "SIGTERM"}),
        (
            "broker.cancellation_requested",
            {"active_workers": 0, "active_connections": 0},
        ),
        ("broker.frozen", {"connections": 1, "leaked_sessions": 0}),
        ("cleanup.pre_snapshot", {"snapshot": snapshot}),
        (
            "state.force_safe",
            {
                "state_before": safe_state,
                "state_after": safe_state,
                "state_changed": False,
            },
        ),
        ("cleanup.post_snapshot", {"snapshot": snapshot}),
        ("lifecycle.summary", terminal),
        (
            "lifecycle.finalized",
            {
                "pre_cleanup_snapshot": snapshot,
                "post_cleanup_snapshot": snapshot,
                **terminal,
            },
        ),
        ("lifecycle.exit", {"code": 0, "safe": True}),
    )
    events = []
    previous = "0" * 64
    for sequence, (kind, fields) in enumerate(definitions, 1):
        item = event(
            sequence,
            previous,
            kind,
            world_id=world_id,
            fields=fields,
        )
        events.append(item)
        previous = item["event_hash"]
    return {
        "events": events,
        "event_count": len(events),
        "final_hash": events[-1]["event_hash"],
        "pre_cleanup_snapshot": snapshot,
        "post_cleanup_snapshot": snapshot,
        "counts": COUNTS,
        "broker": broker,
        "open_sessions": 0,
        "leaked_sessions": 0,
        "safe": True,
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
        "schema_version": 3,
        "source_id": "pyvisa",
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
            "source_id": "pyvisa",
            "id": "pyvisa_dut_validation_v2",
            "protocol_version": 2,
            "run_id": "run-v2",
        },
    }


def rehash(journal_value: dict) -> None:
    previous = "0" * 64
    for item in journal_value["events"]:
        item["previous_hash"] = previous
        unsigned = {
            key: value for key, value in item.items() if key != "event_hash"
        }
        item["event_hash"] = hashlib.sha256(
            json.dumps(
                unsigned,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        previous = item["event_hash"]
    journal_value["final_hash"] = previous


class V2ReportContractTests(unittest.TestCase):
    def test_valid_schema_three_checks_both_siblings_and_journal(self) -> None:
        report = v2_report()
        self.assertIs(
            validate_evaluator_report(
                report, "pyvisa", "pyvisa_dut_validation_v2"
            ),
            report,
        )

    def test_valid_v1_evaluator_report_uses_schema_two(self) -> None:
        report = {
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
            "worlds": [{"container_evidence": container("candidate")}],
            "evaluator": {
                "source_id": "pyvisa",
                "id": "pyvisa_dut_validation_v1",
                "protocol_version": 2,
                "run_id": "run-v1",
            },
        }
        self.assertIs(
            validate_evaluator_report(
                report, "pyvisa", "pyvisa_dut_validation_v1"
            ),
            report,
        )

        invalid_metadata = {
            "wrong evaluator ID": lambda candidate: candidate["evaluator"].update(
                id="pyvisa_dut_validation_v2"
            ),
            "protocol 1": lambda candidate: candidate["evaluator"].update(
                protocol_version=1
            ),
            "empty run ID": lambda candidate: candidate["evaluator"].update(run_id=""),
        }
        for name, mutate in invalid_metadata.items():
            with self.subTest(name=name):
                invalid = {
                    **report,
                    "evaluator": dict(report["evaluator"]),
                }
                mutate(invalid)
                with self.assertRaisesRegex(ContractError, "evaluator identity"):
                    validate_evaluator_report(
                        invalid, "pyvisa", "pyvisa_dut_validation_v1"
                    )

        with self.assertRaisesRegex(ContractError, "run ID"):
            validate_evaluator_report(
                report,
                "pyvisa",
                "pyvisa_dut_validation_v1",
                expected_run_id="another-run",
            )

    def test_report_requires_top_level_and_evaluator_source_identity(self) -> None:
        report = v2_report()
        report["source_id"] = "other"
        with self.assertRaisesRegex(ContractError, "source_id"):
            validate_evaluator_report(
                report, "pyvisa", "pyvisa_dut_validation_v2"
            )

        report = v2_report()
        report["evaluator"]["source_id"] = "other"
        with self.assertRaisesRegex(ContractError, "source_id"):
            validate_evaluator_report(
                report, "pyvisa", "pyvisa_dut_validation_v2"
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
                        report, "pyvisa", "pyvisa_dut_validation_v2"
                    )

    def test_normal_lifecycle_requires_actual_sigterm(self) -> None:
        report = v2_report()
        journal_value = report["worlds"][0]["sim_journal_evidence"]
        signal_event = next(
            item
            for item in journal_value["events"]
            if item["kind"] == "lifecycle.signal"
        )
        signal_event["fields"] = {"signal": "EVENT"}
        rehash(journal_value)
        with self.assertRaisesRegex(ContractError, "lifecycle"):
            validate_evaluator_report(report, "pyvisa", "pyvisa_dut_validation_v2")

    def test_journal_recomputes_counts_and_requires_full_safe_state(self) -> None:
        report = v2_report()
        journal_value = report["worlds"][0]["sim_journal_evidence"]
        journal_value["counts"]["scpi_reads"] = 2
        rehash(journal_value)
        with self.assertRaisesRegex(ContractError, "lifecycle"):
            validate_evaluator_report(report, "pyvisa", "pyvisa_dut_validation_v2")

        report = v2_report()
        journal_value = report["worlds"][0]["sim_journal_evidence"]
        journal_value["events"] = [
            item
            for item in journal_value["events"]
            if item["kind"] != "scpi.read_result"
        ]
        journal_value["event_count"] = len(journal_value["events"])
        journal_value["counts"]["scpi_read_results"] = 0
        for sequence, item in enumerate(journal_value["events"], 1):
            item["sequence"] = sequence
            item["monotonic_ns"] = sequence
        rehash(journal_value)
        with self.assertRaisesRegex(ContractError, "lifecycle"):
            validate_evaluator_report(report, "pyvisa", "pyvisa_dut_validation_v2")

        report = v2_report()
        journal_value = report["worlds"][0]["sim_journal_evidence"]
        journal_value["events"] = [
            item
            for item in journal_value["events"]
            if item["kind"] != "connection.close"
        ]
        journal_value["event_count"] = len(journal_value["events"])
        journal_value["counts"]["connections_closed"] = 0
        for sequence, item in enumerate(journal_value["events"], 1):
            item["sequence"] = sequence
            item["monotonic_ns"] = sequence
        rehash(journal_value)
        with self.assertRaisesRegex(ContractError, "lifecycle"):
            validate_evaluator_report(report, "pyvisa", "pyvisa_dut_validation_v2")

        report = v2_report()
        journal_value = report["worlds"][0]["sim_journal_evidence"]
        journal_value["post_cleanup_snapshot"].pop("awg_points")
        rehash(journal_value)
        with self.assertRaisesRegex(ContractError, "lifecycle"):
            validate_evaluator_report(report, "pyvisa", "pyvisa_dut_validation_v2")

        report = v2_report()
        journal_value = report["worlds"][0]["sim_journal_evidence"]
        forced = next(
            item
            for item in journal_value["events"]
            if item["kind"] == "state.force_safe"
        )
        forced["fields"]["state_after"]["awg"]["output"] = True
        rehash(journal_value)
        with self.assertRaisesRegex(ContractError, "lifecycle"):
            validate_evaluator_report(report, "pyvisa", "pyvisa_dut_validation_v2")

        report = v2_report()
        journal_value = report["worlds"][0]["sim_journal_evidence"]
        journal_value["post_cleanup_snapshot"]["psu_output"] = True
        rehash(journal_value)
        with self.assertRaisesRegex(ContractError, "lifecycle"):
            validate_evaluator_report(report, "pyvisa", "pyvisa_dut_validation_v2")

    def test_evaluator_id_and_missing_valid_sibling_are_rejected(self) -> None:
        report = v2_report()
        report["evaluator"]["id"] = "pyvisa_dut_validation_v1"
        with self.assertRaisesRegex(ContractError, "evaluator"):
            validate_evaluator_report(report, "pyvisa", "pyvisa_dut_validation_v2")

    def test_world_composition_and_current_run_id_are_bound(self) -> None:
        report = v2_report()
        report["worlds"][1] = copy.deepcopy(report["worlds"][0])
        with self.assertRaisesRegex(ContractError, "world|nineteen"):
            validate_evaluator_report(report, "pyvisa", "pyvisa_dut_validation_v2")

        report = v2_report()
        with self.assertRaisesRegex(ContractError, "run"):
            validate_evaluator_report(
                report,
                "pyvisa",
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
            validate_evaluator_report(report, "pyvisa", "pyvisa_dut_validation_v2")

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
            "counts": None,
            "broker": None,
            "open_sessions": None,
            "leaked_sessions": None,
            "safe": None,
            "fatal": {
                **fatal_fields,
                "final_hash": "0" * 64,
            },
        }
        with self.assertRaisesRegex(ContractError, "fatal"):
            validate_evaluator_report(report, "pyvisa", "pyvisa_dut_validation_v2")
        world["sim_journal_evidence"]["fatal"]["final_hash"] = fatal_event[
            "event_hash"
        ]
        self.assertIs(
            validate_evaluator_report(report, "pyvisa", "pyvisa_dut_validation_v2"),
            report,
        )

        report = v2_report()
        report["worlds"][0]["sim_container_evidence"] = None
        with self.assertRaisesRegex(ContractError, "evidence|infrastructure"):
            validate_evaluator_report(report, "pyvisa", "pyvisa_dut_validation_v2")

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
            validate_evaluator_report(report, "pyvisa", "pyvisa_dut_validation_v2"),
            report,
        )
        world["errors"] = []
        with self.assertRaisesRegex(ContractError, "trusted|errors"):
            validate_evaluator_report(report, "pyvisa", "pyvisa_dut_validation_v2")


if __name__ == "__main__":
    unittest.main()
