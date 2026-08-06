from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ContractError(ValueError):
    """A distributed repository or run contract is invalid."""


V2_COUNTED_EVENTS = {
    "connection.open": "connections_opened",
    "connection.close": "connections_closed",
    "connection.reject": "connections_rejected",
    "rpc.request": "rpc_requests",
    "rpc.result": "rpc_results",
    "rpc.reject": "rpc_rejections",
    "resource_query.request": "resource_queries",
    "resource_query.result": "resource_query_results",
    "resource_query.reject": "resource_query_rejections",
    "session.open": "sessions_opened",
    "session.close": "sessions_explicitly_closed",
    "session.forced_cleanup": "sessions_forced_closed",
    "session.invalid_access": "session_invalid_accesses",
    "scpi.write": "scpi_writes",
    "scpi.write_result": "scpi_write_results",
    "scpi.read": "scpi_reads",
    "scpi.read_result": "scpi_read_results",
}


@dataclass(frozen=True)
class RunConfig:
    schema_version: int
    run_id: str
    source_id: str
    instance_checkout: Path
    instance_id: str
    evaluator_checkout: Path
    evaluator_id: str
    candidate_path: Path
    report_path: Path
    timeout_seconds: float
    max_output_bytes: int
    repeated_worlds: int
    repeated_base_seed: int
    container_protocol_version: int
    image_mode: str
    openfibsem_checkout: Path | None = None
    openfibsem_commit: str | None = None


@dataclass(frozen=True)
class RepositoryProvenance:
    path: str
    commit: str
    branch: str
    remote: str | None
    dirty: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "commit": self.commit,
            "branch": self.branch,
            "remote": self.remote,
            "dirty": self.dirty,
        }


def load_run_config(path: Path) -> RunConfig:
    path = path.resolve()
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ContractError(f"cannot load run config: {exc}") from exc
    required = {
        "schema_version",
        "run_id",
        "source_id",
        "instance_checkout",
        "instance_id",
        "evaluator_checkout",
        "evaluator_id",
        "candidate_path",
        "report_path",
        "timeout_seconds",
        "max_output_bytes",
        "repeated_worlds",
        "repeated_base_seed",
        "container_protocol_version",
        "image_mode",
    }
    optional_openfibsem = {"openfibsem_checkout", "openfibsem_commit"}
    if not isinstance(value, dict):
        raise ContractError("run config fields do not match schema version 2")
    is_fibsem = (
        value.get("source_id") == "openfibsem"
        and value.get("evaluator_id") == "fibsem_liftout_v1"
    )
    present_openfibsem = set(value) & optional_openfibsem
    if is_fibsem and present_openfibsem != optional_openfibsem:
        raise ContractError(
            "OpenFIBSEM checkout and commit are both required for FIBSEM"
        )
    if not is_fibsem and present_openfibsem:
        raise ContractError("OpenFIBSEM fields are only valid for FIBSEM")
    expected = required | (optional_openfibsem if is_fibsem else set())
    if set(value) != expected:
        raise ContractError("run config fields do not match schema version 2")
    if value["schema_version"] != 2:
        raise ContractError("unsupported run config schema_version")
    source_id = _identifier(value["source_id"], "source_id")
    instance_id = _identifier(value["instance_id"], "instance_id")
    evaluator_id = _identifier(value["evaluator_id"], "evaluator_id")
    root = path.parent
    instance = _resolve(root, value["instance_checkout"])
    evaluator = _resolve(root, value["evaluator_checkout"])
    candidate = _resolve(root, value["candidate_path"])
    report = _resolve(root, value["report_path"], must_exist=False)
    if not instance.is_dir() or not evaluator.is_dir():
        raise ContractError("instance/evaluator checkout must be a directory")
    if not candidate.is_file():
        raise ContractError("candidate_path must be a file")
    openfibsem: Path | None = None
    openfibsem_commit: str | None = None
    if is_fibsem:
        openfibsem = _resolve(root, value["openfibsem_checkout"])
        if not openfibsem.is_dir():
            raise ContractError("OpenFIBSEM checkout must be a directory")
        openfibsem_commit = _git_commit(value["openfibsem_commit"], "openfibsem_commit")
        if _git(openfibsem, "rev-parse", "--show-toplevel") != str(openfibsem):
            raise ContractError("OpenFIBSEM checkout must be a repository root")
        if _git(openfibsem, "rev-parse", "HEAD") != openfibsem_commit:
            raise ContractError("OpenFIBSEM checkout commit does not match the lock")
        _require_tracked_clean(openfibsem, "OpenFIBSEM")
    container_protocol_version = _protocol_version(
        value["container_protocol_version"], 1, "container_protocol_version"
    )
    return RunConfig(
        schema_version=2,
        run_id=_non_empty(value["run_id"], "run_id"),
        source_id=source_id,
        instance_checkout=instance,
        instance_id=instance_id,
        evaluator_checkout=evaluator,
        evaluator_id=evaluator_id,
        candidate_path=candidate,
        report_path=report,
        timeout_seconds=_positive_number(value["timeout_seconds"], "timeout_seconds"),
        max_output_bytes=_positive_int(value["max_output_bytes"], "max_output_bytes"),
        repeated_worlds=_positive_int(value["repeated_worlds"], "repeated_worlds"),
        repeated_base_seed=_positive_int(
            value["repeated_base_seed"], "repeated_base_seed"
        ),
        container_protocol_version=container_protocol_version,
        image_mode=_exact(value["image_mode"], "locked", "image_mode"),
        openfibsem_checkout=openfibsem,
        openfibsem_commit=openfibsem_commit,
    )


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ContractError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{path} must contain a mapping")
    return value


def repository_provenance(
    path: Path,
    *,
    allow_dirty: bool = False,
    include_untracked: bool = True,
) -> RepositoryProvenance:
    root = path.resolve()
    if _git(root, "rev-parse", "--show-toplevel") != str(root):
        raise ContractError(f"not a repository root: {root}")
    status_arguments = ["status", "--porcelain"]
    if not include_untracked:
        status_arguments.append("--untracked-files=no")
    status = _git(root, *status_arguments)
    dirty = bool(status)
    if dirty and not allow_dirty:
        raise ContractError(f"repository is dirty: {root}")
    remote = _git_optional(root, "remote", "get-url", "origin")
    return RepositoryProvenance(
        path=str(root),
        commit=_git(root, "rev-parse", "HEAD"),
        branch=_git(root, "branch", "--show-current"),
        remote=remote,
        dirty=dirty,
    )


def validate_dependencies(
    source_id: str,
    instance: dict[str, Any],
    evaluator: dict[str, Any],
) -> None:
    if instance.get("source_id") != source_id:
        raise ContractError("instance source_id mismatch")
    if evaluator.get("source_id") != source_id:
        raise ContractError("evaluator source_id mismatch")
    instance_id = instance.get("instance_id")
    evaluator_contract = instance.get("evaluator")
    if not isinstance(evaluator_contract, dict):
        raise ContractError("instance evaluator contract is missing")
    if evaluator_contract.get("id") != evaluator.get("evaluator_id"):
        raise ContractError("evaluator id mismatch")
    _protocol_version(
        evaluator_contract.get("protocol_version"), 2, "instance evaluator protocol"
    )
    _protocol_version(
        evaluator.get("protocol_version"), 2, "evaluator protocol"
    )
    if instance_id not in evaluator.get("supported_instances", []):
        raise ContractError("instance is not supported by evaluator")
    container = instance.get("container")
    if not isinstance(container, dict):
        raise ContractError("instance container contract is missing")
    _protocol_version(container.get("protocol_version"), 1, "instance container protocol")
    _protocol_version(
        evaluator.get("container_protocol_version"), 1, "evaluator container protocol"
    )
    if evaluator.get("candidate_execution") != "docker":
        raise ContractError("evaluator must require Docker candidate execution")
    if evaluator.get("image_mode") != "locked":
        raise ContractError("evaluator image mode must be locked")


def validate_visible_hashes(instance_root: Path, manifest: dict[str, Any]) -> None:
    visible = manifest.get("visible_files")
    if not isinstance(visible, dict) or not visible:
        raise ContractError("visible_files must be a non-empty hash mapping")
    for relative, expected in visible.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ContractError("visible_files entries must be string hashes")
        path = (instance_root / relative).resolve()
        if not path.is_relative_to(instance_root.resolve()) or not path.is_file():
            raise ContractError(f"invalid visible file: {relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ContractError(f"visible file hash mismatch: {relative}")


REPORT_SCHEMA_VERSIONS = {
    ("pyvisa", "pyvisa_dut_validation_v1"): 2,
    ("pyvisa", "pyvisa_dut_validation_v2"): 3,
    ("openfibsem", "fibsem_liftout_v1"): 4,
}


def validate_evaluator_report(
    value: Any,
    source_id: str,
    evaluator_id: str,
    *,
    expected_run_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("evaluator report must be an object")
    expected_schema = REPORT_SCHEMA_VERSIONS.get((source_id, evaluator_id))
    if expected_schema is None:
        raise ContractError("unsupported evaluator report identity")
    if value.get("source_id") != source_id:
        raise ContractError("report source_id does not match evaluator")
    if (source_id, evaluator_id) == ("openfibsem", "fibsem_liftout_v1"):
        _validate_fibsem_report(value)
        return value
    required = {
        "schema_version",
        "source_id",
        "status",
        "strict_pass",
        "score",
        "dimensions",
        "strict_gates",
        "evidence_confidence",
        "worlds",
        "infrastructure_valid",
        "retry_eligible",
        "evaluator",
    }
    missing = sorted(required - set(value))
    if missing:
        raise ContractError(f"evaluator report missing: {', '.join(missing)}")
    if value["schema_version"] != expected_schema:
        raise ContractError("report schema_version does not match evaluator")
    _validate_non_fibsem_evaluator_metadata(
        value, source_id, evaluator_id, expected_run_id=expected_run_id
    )
    try:
        valid_score = (
            not isinstance(value["score"], bool)
            and 0 <= float(value["score"]) <= 100
        )
    except (TypeError, ValueError, OverflowError):
        valid_score = False
    if not valid_score:
        raise ContractError("report score must be between 0 and 100")
    worlds = value["worlds"]
    if not isinstance(worlds, list) or not worlds:
        raise ContractError("evaluator report worlds must be non-empty")
    if evaluator_id == "pyvisa_dut_validation_v2":
        _validate_v2_report(value, worlds)
        return value
    _validate_v1_worlds(worlds)
    return value


def _validate_non_fibsem_evaluator_metadata(
    report: dict[str, Any],
    source_id: str,
    evaluator_id: str,
    *,
    expected_run_id: str | None,
) -> None:
    evaluator = report.get("evaluator")
    if not isinstance(evaluator, dict) or evaluator.get("source_id") != source_id:
        raise ContractError("report evaluator source_id does not match evaluator")
    if (
        evaluator.get("id") != evaluator_id
        or evaluator.get("protocol_version") != 2
        or not isinstance(evaluator.get("run_id"), str)
        or not evaluator["run_id"]
    ):
        raise ContractError("report evaluator identity is invalid")
    if expected_run_id is not None and evaluator["run_id"] != expected_run_id:
        raise ContractError("report run ID does not match this run")


def _validate_fibsem_report(report: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "source_id",
        "evaluator_id",
        "openfibsem_commit",
        "score",
        "strict_pass",
        "retry_eligible",
        "strict_gates",
        "dimension_scores",
        "evidence_confidence",
        "suite",
        "worlds",
    }
    if set(report) != required:
        raise ContractError("FIBSEM report fields are invalid")
    if (
        report["schema_version"] != 4
        or report["source_id"] != "openfibsem"
        or report["evaluator_id"] != "fibsem_liftout_v1"
        or not _is_git_commit(report["openfibsem_commit"])
        or not isinstance(report["strict_pass"], bool)
        or not isinstance(report["retry_eligible"], bool)
        or report["suite"] != {"fixed_worlds": 5, "seeded_worlds": 5}
    ):
        raise ContractError("FIBSEM report identity or suite is invalid")
    _nullable_score(
        report["score"],
        "FIBSEM suite score",
        nullable=report["retry_eligible"],
    )
    if not _boolean_mapping(report["strict_gates"]):
        raise ContractError("FIBSEM strict gates are invalid")
    dimensions = report["dimension_scores"]
    if not isinstance(dimensions, dict) or set(dimensions) != {
        "step_1",
        "step_2",
        "step_3",
        "step_4",
        "artifacts",
    }:
        raise ContractError("FIBSEM dimension scores are invalid")
    for name, maximum in {
        "step_1": 20,
        "step_2": 25,
        "step_3": 25,
        "step_4": 20,
        "artifacts": 10,
    }.items():
        _bounded_score(dimensions[name], f"FIBSEM {name}", maximum)
    confidence = report["evidence_confidence"]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(float(confidence))
        or not 0 <= float(confidence) <= 1
    ):
        raise ContractError("FIBSEM evidence confidence is invalid")
    worlds = report["worlds"]
    expected_ids = (
        "nominal",
        "small",
        "large",
        "needle_offset",
        "target_pose",
        "seeded_01",
        "seeded_02",
        "seeded_03",
        "seeded_04",
        "seeded_05",
    )
    if (
        not isinstance(worlds, list)
        or tuple(
            world.get("world_id") if isinstance(world, dict) else None
            for world in worlds
        )
        != expected_ids
    ):
        raise ContractError("FIBSEM report must contain the exact ten worlds")
    retries: list[bool] = []
    for index, world in enumerate(worlds):
        assert isinstance(world, dict)
        _validate_fibsem_world(world, index)
        retries.append(world["retry_eligible"])
    if report["retry_eligible"] != any(retries):
        raise ContractError("FIBSEM retry eligibility is inconsistent")
    if report["strict_pass"] and (
        report["score"] is None
        or float(report["score"]) < 90
        or not all(report["strict_gates"].values())
    ):
        raise ContractError("FIBSEM strict pass contradicts suite evidence")


def _validate_fibsem_world(world: dict[str, Any], index: int) -> None:
    required = {
        "world_id",
        "category",
        "score",
        "strict_pass",
        "retry_eligible",
        "step_scores",
        "artifact_score",
        "strict_gates",
        "checkpoints",
        "partial_order",
        "terminal",
        "runtime",
        "evidence_confidence",
        "candidate_container_evidence",
        "sim_container_evidence",
        "trusted_evidence",
    }
    world_id = world.get("world_id")
    if set(world) != required or not isinstance(world_id, str):
        raise ContractError(f"FIBSEM world {index} fields are invalid")
    retry = world.get("retry_eligible")
    if not isinstance(world.get("strict_pass"), bool) or not isinstance(retry, bool):
        raise ContractError(f"FIBSEM world {world_id} status is invalid")
    expected_category = (
        "fixed"
        if world_id in {"nominal", "small", "large", "needle_offset", "target_pose"}
        else "seeded"
    )
    if world.get("category") != expected_category or not _boolean_mapping(
        world.get("strict_gates")
    ):
        raise ContractError(f"FIBSEM world {world_id} gates or category are invalid")
    _nullable_score(world.get("score"), f"FIBSEM world {world_id}", nullable=retry)
    steps = world.get("step_scores")
    if not isinstance(steps, dict) or set(steps) != {
        "step_1",
        "step_2",
        "step_3",
        "step_4",
    }:
        raise ContractError(f"FIBSEM world {world_id} step scores are invalid")
    for step, maximum in {
        "step_1": 20,
        "step_2": 25,
        "step_3": 25,
        "step_4": 20,
    }.items():
        _bounded_score(steps[step], f"FIBSEM {world_id}/{step}", maximum)
    _bounded_score(world.get("artifact_score"), f"FIBSEM {world_id}/artifacts", 10)
    checkpoints = world.get("checkpoints")
    checkpoint_order = ["step_1", "step_2", "step_3", "step_4"]
    if (
        not isinstance(checkpoints, dict)
        or list(checkpoints) != checkpoint_order[: len(checkpoints)]
        or world.get("strict_pass")
        and len(checkpoints) != 4
    ):
        raise ContractError(f"FIBSEM checkpoint evidence is incomplete: {world_id}")
    for step, checkpoint in checkpoints.items():
        if (
            not isinstance(checkpoint, dict)
            or checkpoint.get("step_id") != step
            or checkpoint.get("artifact_complete") is not True
            or not _is_raw_sha256(checkpoint.get("artifact_digest"))
            or not isinstance(checkpoint.get("geometry"), dict)
            or not _is_raw_sha256(
                checkpoint["geometry"].get("canonical_geometry_hash")
            )
        ):
            raise ContractError(f"FIBSEM checkpoint evidence is invalid: {world_id}/{step}")
    candidate = world.get("candidate_container_evidence")
    sim = world.get("sim_container_evidence")
    trusted = world.get("trusted_evidence")
    if not retry and any(value is None for value in (candidate, sim, trusted)):
        raise ContractError(f"FIBSEM sibling evidence is incomplete: {world_id}")
    if candidate is not None:
        _validate_v2_container(
            candidate, index=index, role="candidate", require_cleanup=not retry
        )
    if sim is not None:
        _validate_v2_container(sim, index=index, role="sim", require_cleanup=not retry)
    if trusted is not None:
        if (
            not isinstance(trusted, dict)
            or set(trusted)
            != {
                "journal_head_hash",
                "journal_event_count",
                "outcome",
                "forced_cleanup",
                "scenario_digest",
            }
            or not _is_raw_sha256(trusted["journal_head_hash"])
            or not _is_raw_sha256(trusted["scenario_digest"])
            or isinstance(trusted["journal_event_count"], bool)
            or not isinstance(trusted["journal_event_count"], int)
            or trusted["journal_event_count"] < 1
            or not isinstance(trusted["forced_cleanup"], bool)
            or trusted.get("outcome")
            not in {
                "completed",
                "candidate_incomplete",
                "candidate_failure",
                "infrastructure_failure",
                "cleanup_failure",
            }
        ):
            raise ContractError(f"FIBSEM trusted evidence is invalid: {world_id}")
    runtime = world.get("runtime")
    terminal = world.get("terminal")
    partial_order = world.get("partial_order")
    confidence = world.get("evidence_confidence")
    runtime_fields = {
        "candidate_exit_code",
        "timed_out",
        "forbidden_access",
        "infrastructure_failure",
        "candidate_uid",
        "simulator_uid",
        "isolation_verified",
    }
    partial_fields = {
        "preflight",
        "destructive_roi",
        "step_1",
        "needle_joint",
        "source_separation",
        "carry",
        "step_2",
        "transfer",
        "target_pose",
        "target_joint",
        "step_3",
        "needle_separation",
        "needle_retraction",
        "step_4",
    }
    if (
        not isinstance(runtime, dict)
        or set(runtime) != runtime_fields
        or runtime.get("candidate_uid") != 10001
        or runtime.get("simulator_uid") != 11001
        or any(
            not isinstance(runtime.get(name), bool)
            for name in (
                "timed_out",
                "forbidden_access",
                "infrastructure_failure",
                "isolation_verified",
            )
        )
        or not isinstance(terminal, dict)
        or set(terminal) != {"safe", "simulator_idle", "collision", "cleanup_error"}
        or any(
            not isinstance(terminal.get(name), bool)
            for name in ("safe", "simulator_idle", "collision")
        )
        or terminal.get("cleanup_error") is not None
        and not isinstance(terminal.get("cleanup_error"), str)
        or not isinstance(partial_order, dict)
        or set(partial_order) != partial_fields
        or any(
            value is not None
            and (isinstance(value, bool) or not isinstance(value, int) or value < 1)
            for value in partial_order.values()
        )
        or isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(float(confidence))
        or not 0 <= float(confidence) <= 1
    ):
        raise ContractError(f"FIBSEM runtime or terminal evidence is invalid: {world_id}")
    exit_code = runtime["candidate_exit_code"]
    if exit_code is not None and (
        isinstance(exit_code, bool) or not isinstance(exit_code, int)
    ):
        raise ContractError(f"FIBSEM candidate exit code is invalid: {world_id}")
    if world["strict_pass"] and (
        len(checkpoints) != 4
        or not all(world["strict_gates"].values())
        or terminal != {
            "safe": True,
            "simulator_idle": True,
            "collision": False,
            "cleanup_error": None,
        }
        or runtime["candidate_exit_code"] != 0
        or runtime["timed_out"]
        or runtime["forbidden_access"]
        or runtime["infrastructure_failure"]
        or not runtime["isolation_verified"]
        or trusted is None
        or trusted["outcome"] != "completed"
        or trusted["forced_cleanup"]
    ):
        raise ContractError(f"FIBSEM strict world contradicts evidence: {world_id}")


def _nullable_score(value: Any, name: str, *, nullable: bool) -> None:
    if value is None and nullable:
        return
    _bounded_score(value, name, 100)


def _bounded_score(value: Any, name: str, maximum: float) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0 <= float(value) <= maximum
    ):
        raise ContractError(f"{name} score is invalid")


def _boolean_mapping(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and bool(value)
        and all(isinstance(key, str) and isinstance(item, bool) for key, item in value.items())
    )


def _validate_v1_worlds(worlds: list[Any]) -> None:
    for index, world in enumerate(worlds):
        if not isinstance(world, dict):
            raise ContractError(f"world {index} must be an object")
        container = world.get("container_evidence")
        if not isinstance(container, dict):
            raise ContractError(f"world {index} missing container evidence")
        required_security = {
            "container_id",
            "image_digest",
            "network_mode",
            "readonly_rootfs",
            "user",
            "cleanup_succeeded",
        }
        if not required_security.issubset(container):
            raise ContractError(f"world {index} container evidence is incomplete")
        if (
            not isinstance(container["image_digest"], str)
            or not container["image_digest"].startswith("sha256:")
        ):
            raise ContractError(f"world {index} image digest is invalid")
        if container["network_mode"] != "none" or not container["readonly_rootfs"]:
            raise ContractError(f"world {index} Docker security evidence failed")
        if container["user"] != "10001:10001":
            raise ContractError(f"world {index} container user is invalid")
        if container["cleanup_succeeded"] is not True:
            raise ContractError(f"world {index} cleanup evidence failed")


def _validate_v2_report(report: dict[str, Any], worlds: list[Any]) -> None:
    if (
        not isinstance(report.get("infrastructure_valid"), bool)
        or not isinstance(report.get("retry_eligible"), bool)
    ):
        raise ContractError("v2 aggregate infrastructure status is invalid")
    evaluator = report.get("evaluator")
    assert isinstance(evaluator, dict)
    expected_world_ids = (
        "nominal",
        "reordered_resources",
        "distractor_devices",
        "numeric_formats",
        "binary_block_variants",
        "delayed_settle",
        "dirty_initial_state",
        "dut_gain_failure",
        "command_error",
        *(f"repeated_{index:03d}" for index in range(10)),
    )
    actual_world_ids = tuple(
        world.get("world_id") if isinstance(world, dict) else None
        for world in worlds
    )
    if actual_world_ids != expected_world_ids:
        raise ContractError("v2 report world composition is invalid")
    validities: list[bool] = []
    retries: list[bool] = []
    for index, raw_world in enumerate(worlds):
        if not isinstance(raw_world, dict):
            raise ContractError(f"world {index} must be an object")
        world = raw_world
        world_id = world.get("world_id")
        infrastructure_valid = world.get("infrastructure_valid")
        retry_eligible = world.get("retry_eligible")
        errors = world.get("errors")
        if (
            not isinstance(world_id, str)
            or not world_id
            or not isinstance(infrastructure_valid, bool)
            or not isinstance(retry_eligible, bool)
            or not isinstance(errors, list)
            or not all(isinstance(error, str) for error in errors)
        ):
            raise ContractError(f"world {index} v2 status evidence is invalid")
        validities.append(infrastructure_valid)
        retries.append(retry_eligible)
        if infrastructure_valid and retry_eligible:
            raise ContractError(f"world {index} valid infrastructure cannot retry")
        if not infrastructure_valid and (
            world.get("status") != "infrastructure_failure"
            or not retry_eligible
            or not any(error for error in errors)
        ):
            raise ContractError(
                f"world {index} infrastructure failure status and errors are required"
            )
        candidate = world.get("candidate_container_evidence")
        sim = world.get("sim_container_evidence")
        journal = world.get("sim_journal_evidence")
        missing = any(value is None for value in (candidate, sim, journal))
        if missing and (infrastructure_valid or not retry_eligible):
            raise ContractError(
                f"world {index} missing sibling evidence requires infrastructure failure"
            )
        if candidate is not None:
            _validate_v2_container(
                candidate,
                index=index,
                role="candidate",
                require_cleanup=infrastructure_valid,
            )
        if sim is not None:
            _validate_v2_container(
                sim,
                index=index,
                role="sim",
                require_cleanup=infrastructure_valid,
            )
        if journal is not None:
            _validate_v2_journal(
                journal,
                index=index,
                run_id=evaluator["run_id"],
                world_id=world_id,
                allow_fatal=not infrastructure_valid,
            )
    if report.get("infrastructure_valid") != all(validities):
        raise ContractError("v2 aggregate infrastructure validity is inconsistent")
    if report.get("retry_eligible") != any(retries):
        raise ContractError("v2 aggregate retry eligibility is inconsistent")


def _validate_v2_container(
    value: Any,
    *,
    index: int,
    role: str,
    require_cleanup: bool,
) -> None:
    if not isinstance(value, dict):
        raise ContractError(f"world {index} {role} container evidence is invalid")
    required = {
        "container_id",
        "image_digest",
        "network_mode",
        "readonly_rootfs",
        "user",
        "cap_drop",
        "security_options",
        "mounts",
        "cleanup_attempted",
        "cleanup_succeeded",
    }
    if role == "candidate":
        required.add("candidate_status")
    if not required.issubset(value):
        raise ContractError(f"world {index} {role} container evidence is incomplete")
    digest = value["image_digest"]
    user = "10001:10001" if role == "candidate" else "11001:11001"
    if (
        not _is_sha256_image(digest)
        or value["network_mode"] != "none"
        or value["readonly_rootfs"] is not True
        or value["user"] != user
        or not isinstance(value["cap_drop"], list)
        or "ALL" not in value["cap_drop"]
        or not isinstance(value["security_options"], list)
        or "no-new-privileges" not in value["security_options"]
        or value["cleanup_attempted"] is not True
        or (require_cleanup and value["cleanup_succeeded"] is not True)
    ):
        raise ContractError(f"world {index} {role} container security failed")
    if role == "candidate" and (
        not isinstance(value["candidate_status"], str)
        or not value["candidate_status"]
    ):
        raise ContractError(f"world {index} candidate status is invalid")
    expected = (
        {
            "/workspace": False,
            "/runner": False,
            "/run/iab": False,
        }
        if role == "candidate"
        else {
            "/run/iab/transport": True,
            "/run/iab/evidence": True,
            "/run/iab/world.json": False,
        }
    )
    mounts = value["mounts"]
    if not isinstance(mounts, list) or len(mounts) != len(expected):
        raise ContractError(f"world {index} {role} mount allowlist failed")
    actual: dict[str, bool] = {}
    for mount in mounts:
        if (
            not isinstance(mount, dict)
            or mount.get("type") != "bind"
            or not isinstance(mount.get("destination"), str)
            or not isinstance(mount.get("writable"), bool)
        ):
            raise ContractError(f"world {index} {role} mount evidence is invalid")
        destination = mount["destination"]
        if destination in actual:
            raise ContractError(f"world {index} {role} mount is duplicated")
        actual[destination] = mount["writable"]
    if actual != expected:
        raise ContractError(f"world {index} {role} mount allowlist failed")


def _validate_v2_journal(
    value: Any,
    *,
    index: int,
    run_id: str,
    world_id: str,
    allow_fatal: bool,
) -> None:
    if not isinstance(value, dict):
        raise ContractError(f"world {index} sim journal evidence is invalid")
    required = {
        "events",
        "event_count",
        "final_hash",
        "pre_cleanup_snapshot",
        "post_cleanup_snapshot",
        "counts",
        "broker",
        "open_sessions",
        "leaked_sessions",
        "safe",
        "fatal",
    }
    if set(value) != required:
        raise ContractError(f"world {index} sim journal evidence is incomplete")
    events = value["events"]
    count = value["event_count"]
    if (
        not isinstance(events, list)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count != len(events)
    ):
        raise ContractError(f"world {index} sim journal event count mismatch")
    previous = "0" * 64
    previous_time = -1
    for sequence, raw_event in enumerate(events, 1):
        if not isinstance(raw_event, dict):
            raise ContractError(f"world {index} sim journal event is invalid")
        expected = {
            "run_id",
            "world_id",
            "sequence",
            "monotonic_ns",
            "previous_hash",
            "kind",
            "fields",
            "event_hash",
        }
        if set(raw_event) != expected:
            raise ContractError(f"world {index} sim journal event shape is invalid")
        monotonic = raw_event["monotonic_ns"]
        if (
            raw_event["run_id"] != run_id
            or raw_event["world_id"] != world_id
            or raw_event["sequence"] != sequence
            or isinstance(raw_event["sequence"], bool)
            or isinstance(monotonic, bool)
            or not isinstance(monotonic, int)
            or monotonic < previous_time
            or raw_event["previous_hash"] != previous
            or not isinstance(raw_event["kind"], str)
            or not raw_event["kind"]
            or not isinstance(raw_event["fields"], dict)
        ):
            raise ContractError(f"world {index} sim journal chain is invalid")
        unsigned = {
            key: item for key, item in raw_event.items() if key != "event_hash"
        }
        try:
            payload = json.dumps(
                unsigned,
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ContractError(
                f"world {index} sim journal event is not canonical JSON"
            ) from exc
        digest = hashlib.sha256(payload).hexdigest()
        if raw_event["event_hash"] != digest:
            raise ContractError(f"world {index} sim journal hash mismatch")
        previous = digest
        previous_time = monotonic
    final_hash = value["final_hash"]
    expected_hash = previous if events else None
    if final_hash != expected_hash:
        raise ContractError(f"world {index} sim journal terminal hash mismatch")
    fatal = value["fatal"]
    if fatal is None:
        _validate_v2_normal_lifecycle(
            events,
            pre_cleanup=value["pre_cleanup_snapshot"],
            post_cleanup=value["post_cleanup_snapshot"],
            counts=value["counts"],
            broker=value["broker"],
            open_sessions=value["open_sessions"],
            leaked_sessions=value["leaked_sessions"],
            safe=value["safe"],
            index=index,
        )
        return
    if not allow_fatal:
        raise ContractError(f"world {index} valid infrastructure has fatal evidence")
    _validate_v2_fatal(
        fatal,
        events=events,
        final_hash=final_hash,
        index=index,
        run_id=run_id,
        pre_cleanup=value["pre_cleanup_snapshot"],
        post_cleanup=value["post_cleanup_snapshot"],
        counts=value["counts"],
        broker=value["broker"],
        open_sessions=value["open_sessions"],
        leaked_sessions=value["leaked_sessions"],
        safe=value["safe"],
    )


def _validate_v2_normal_lifecycle(
    events: list[dict[str, Any]],
    *,
    pre_cleanup: Any,
    post_cleanup: Any,
    counts: Any,
    broker: Any,
    open_sessions: Any,
    leaked_sessions: Any,
    safe: Any,
    index: int,
) -> None:
    required = (
        "lifecycle.start",
        "lifecycle.configuration",
        "lifecycle.socket_bound",
        "broker.ready",
        "lifecycle.signal",
        "broker.cancellation_requested",
        "broker.frozen",
        "cleanup.pre_snapshot",
        "state.force_safe",
        "cleanup.post_snapshot",
        "lifecycle.summary",
        "lifecycle.finalized",
        "lifecycle.exit",
    )
    kinds = [event["kind"] for event in events]
    if (
        not events
        or events[0]["kind"] != "lifecycle.start"
        or events[-1]["kind"] != "lifecycle.exit"
        or any(kinds.count(kind) != 1 for kind in required)
        or [kinds.index(kind) for kind in required]
        != sorted(kinds.index(kind) for kind in required)
        or not _valid_v2_snapshot(pre_cleanup)
        or not _valid_v2_snapshot(post_cleanup)
        or post_cleanup["safe"] is not True
        or any(
            kind
            in {
                "trusted.failure_detected",
                "trusted.fatal",
                "cleanup.failure",
            }
            for kind in kinds
        )
    ):
        raise ContractError(
            f"world {index} sim journal lifecycle is incomplete"
        )
    fields = {kind: events[kinds.index(kind)]["fields"] for kind in required}
    configuration = fields["lifecycle.configuration"]
    broker_frozen = fields["broker.frozen"]
    cancellation = fields["broker.cancellation_requested"]
    derived_broker = {
        "connections": broker_frozen.get("connections"),
        "leaked_sessions": broker_frozen.get("leaked_sessions"),
        "frozen": True,
    }
    derived_counts = {name: 0 for name in V2_COUNTED_EVENTS.values()}
    for raw_event in events:
        name = V2_COUNTED_EVENTS.get(raw_event["kind"])
        if name is not None:
            derived_counts[name] += 1
    derived_open = (
        derived_counts["sessions_opened"]
        - derived_counts["sessions_explicitly_closed"]
        - derived_counts["sessions_forced_closed"]
    )
    force_safe = fields["state.force_safe"]
    safe_state = force_safe.get("state_after")
    psu = safe_state.get("psu") if isinstance(safe_state, dict) else None
    awg = safe_state.get("awg") if isinstance(safe_state, dict) else None
    switch = safe_state.get("switch") if isinstance(safe_state, dict) else None
    terminal_fields = {
        "broker": derived_broker,
        "counts": derived_counts,
        "open_sessions": 0,
        "leaked_sessions": derived_counts["sessions_forced_closed"],
        "safe": True,
        "fatal": None,
    }
    if (
        set(configuration) != {"world_sha256", "simulator_sha256"}
        or not all(_is_raw_sha256(configuration[name]) for name in configuration)
        or fields["lifecycle.socket_bound"]
        != {"endpoint_name": "visa.sock", "mode": "0666"}
        or fields["lifecycle.signal"] != {"signal": "SIGTERM"}
        or set(cancellation) != {"active_workers", "active_connections"}
        or not all(
            isinstance(cancellation[name], int)
            and not isinstance(cancellation[name], bool)
            and cancellation[name] >= 0
            for name in cancellation
        )
        or set(broker_frozen) != {"connections", "leaked_sessions"}
        or not all(
            isinstance(broker_frozen[name], int)
            and not isinstance(broker_frozen[name], bool)
            and broker_frozen[name] >= 0
            for name in broker_frozen
        )
        or fields["cleanup.pre_snapshot"] != {"snapshot": pre_cleanup}
        or fields["cleanup.post_snapshot"] != {"snapshot": post_cleanup}
        or not isinstance(safe_state, dict)
        or not isinstance(psu, dict)
        or psu.get("output") is not False
        or not isinstance(awg, dict)
        or awg.get("output") is not False
        or not isinstance(switch, dict)
        or switch.get("closed_routes") != []
        or counts != derived_counts
        or broker != derived_broker
        or open_sessions != derived_open
        or isinstance(open_sessions, bool)
        or open_sessions != 0
        or leaked_sessions != derived_counts["sessions_forced_closed"]
        or leaked_sessions != derived_broker["leaked_sessions"]
        or derived_counts["connections_opened"] != derived_broker["connections"]
        or derived_counts["connections_closed"]
        != derived_counts["connections_opened"]
        or derived_counts["rpc_requests"]
        != derived_counts["rpc_results"] + derived_counts["rpc_rejections"]
        or derived_counts["resource_queries"]
        != derived_counts["resource_query_results"]
        + derived_counts["resource_query_rejections"]
        or safe is not True
        or fields["lifecycle.summary"] != terminal_fields
        or fields["lifecycle.finalized"]
        != {
            "pre_cleanup_snapshot": pre_cleanup,
            "post_cleanup_snapshot": post_cleanup,
            **terminal_fields,
        }
        or fields["lifecycle.exit"] != {"code": 0, "safe": True}
        or not _valid_v2_rpc_boundaries(events)
    ):
        raise ContractError(
            f"world {index} sim journal lifecycle evidence is invalid"
        )


def _valid_v2_snapshot(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "clock_ms",
        "closed_routes",
        "psu_voltage_v",
        "psu_output",
        "awg_waveform_name",
        "awg_points",
        "awg_amplitude_vpp",
        "awg_output",
        "stimulus_started_ms",
        "safe",
    }:
        return False
    if (
        isinstance(value["clock_ms"], bool)
        or not isinstance(value["clock_ms"], int)
        or value["clock_ms"] < 0
    ):
        return False
    started = value["stimulus_started_ms"]
    if started is not None and (
        isinstance(started, bool)
        or not isinstance(started, int)
        or started < 0
    ):
        return False
    if not all(
        isinstance(value[name], bool)
        for name in ("psu_output", "awg_output", "safe")
    ):
        return False
    waveform = value["awg_waveform_name"]
    if waveform is not None and not isinstance(waveform, str):
        return False
    routes = value["closed_routes"]
    points = value["awg_points"]
    return (
        isinstance(routes, list)
        and all(isinstance(route, str) and route for route in routes)
        and isinstance(points, list)
        and len(points) <= 64
        and all(_finite_v2_number(point) for point in points)
        and _finite_v2_number(value["psu_voltage_v"])
        and _finite_v2_number(value["awg_amplitude_vpp"])
        and value["safe"]
        is (
            not value["psu_output"]
            and not value["awg_output"]
            and not routes
        )
    )


def _valid_v2_rpc_boundaries(events: list[dict[str, Any]]) -> bool:
    tracked = {
        "rpc.request",
        "rpc.result",
        "rpc.reject",
        "scpi.write",
        "scpi.write_result",
        "scpi.read",
        "scpi.read_result",
    }
    per_connection: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if event["kind"] not in tracked:
            continue
        connection = event["fields"].get("connection_id")
        if not isinstance(connection, str) or not connection:
            return False
        per_connection.setdefault(connection, []).append(event)
    for stream in per_connection.values():
        operation: Any = None
        scpi: list[str] = []
        for event in stream:
            kind = event["kind"]
            if kind == "rpc.request":
                if operation is not None:
                    return False
                operation = event["fields"].get("operation")
                scpi = []
                continue
            if kind.startswith("scpi."):
                if operation is None:
                    return False
                scpi.append(kind)
                continue
            if operation is None:
                return False
            if event["fields"].get("operation") != operation:
                return False
            if isinstance(operation, str) and operation in {"read", "write"}:
                attempt = f"scpi.{operation}"
                result = f"{attempt}_result"
                if kind == "rpc.result":
                    if scpi != [attempt, result]:
                        return False
                elif scpi not in ([], [attempt]):
                    return False
            elif scpi:
                return False
            operation = None
            scpi = []
        if operation is not None:
            return False
    return True


def _finite_v2_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _is_raw_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _validate_v2_fatal(
    fatal: Any,
    *,
    events: list[Any],
    final_hash: Any,
    index: int,
    run_id: str,
    pre_cleanup: Any,
    post_cleanup: Any,
    counts: Any,
    broker: Any,
    open_sessions: Any,
    leaked_sessions: Any,
    safe: Any,
) -> None:
    required = {
        "schema_version",
        "run_id",
        "failure_kind",
        "exception_type",
        "message",
    }
    expected_fields = required | ({"final_hash"} if events else set())
    if (
        not isinstance(fatal, dict)
        or set(fatal) != expected_fields
        or fatal.get("schema_version") != 1
        or isinstance(fatal.get("schema_version"), bool)
        or fatal.get("run_id") != run_id
        or fatal.get("failure_kind") != "trusted_sim_failure"
        or not isinstance(fatal.get("exception_type"), str)
        or not fatal["exception_type"]
        or not isinstance(fatal.get("message"), str)
        or not fatal["message"]
        or pre_cleanup is not None
        or post_cleanup is not None
        or counts is not None
        or broker is not None
        or open_sessions is not None
        or leaked_sessions is not None
        or safe is not None
    ):
        raise ContractError(f"world {index} sim fatal evidence is invalid")
    if events and (
        fatal["final_hash"] != final_hash
        or events[-1]["kind"] != "trusted.fatal"
        or events[-1]["fields"]
        != {key: item for key, item in fatal.items() if key != "final_hash"}
    ):
        raise ContractError(f"world {index} sim fatal evidence does not match journal")


def _is_sha256_image(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(
        character in "0123456789abcdef" for character in digest
    )


def validate_evaluator_container_evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("evaluator container evidence must be an object")
    required = {
        "container_id",
        "image_id",
        "dockerfile_sha256",
        "build_manifest_sha256",
        "network_mode",
        "readonly_rootfs",
        "user",
        "cap_drop",
        "security_options",
        "mounts",
        "cleanup_succeeded",
    }
    if not required.issubset(value):
        raise ContractError("evaluator container evidence is incomplete")
    for name in ("image_id",):
        if not isinstance(value[name], str) or not value[name].startswith("sha256:"):
            raise ContractError(f"evaluator container {name} is invalid")
    for name in ("dockerfile_sha256", "build_manifest_sha256"):
        digest = value[name]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ContractError(f"evaluator container {name} is invalid")
    mounts = value["mounts"]
    socket_mounts = (
        [mount for mount in mounts if mount.get("Destination") == "/var/run/docker.sock"]
        if isinstance(mounts, (list, tuple))
        and all(isinstance(mount, dict) for mount in mounts)
        else []
    )
    checks = (
        bool(value["container_id"]),
        value["network_mode"] == "none",
        value["readonly_rootfs"] is True,
        value["user"] == "11001:11001",
        "ALL" in value["cap_drop"],
        "no-new-privileges" in value["security_options"],
        len(socket_mounts) == 1,
        value["cleanup_succeeded"] is True,
    )
    if not all(checks):
        raise ContractError("evaluator container security evidence failed")
    return value


def dump_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _git(path: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise ContractError(completed.stderr.strip() or "git command failed")
    return completed.stdout.strip()


def _git_optional(path: Path, *arguments: str) -> str | None:
    try:
        value = _git(path, *arguments)
    except ContractError:
        return None
    return value or None


def _resolve(root: Path, raw: Any, *, must_exist: bool = True) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ContractError("path values must be non-empty strings")
    path = Path(raw)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if must_exist and not resolved.exists():
        raise ContractError(f"path does not exist: {resolved}")
    return resolved


def _non_empty(raw: Any, name: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise ContractError(f"{name} must be a non-empty string")
    return raw


def _identifier(raw: Any, name: str) -> str:
    if not isinstance(raw, str) or re.fullmatch(
        r"[a-z][a-z0-9_-]*", raw
    ) is None:
        raise ContractError(f"invalid {name}")
    return raw


def _positive_number(raw: Any, name: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw <= 0:
        raise ContractError(f"{name} must be positive")
    return float(raw)


def _positive_int(raw: Any, name: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ContractError(f"{name} must be a positive integer")
    return raw


def _protocol_version(raw: Any, expected: int, name: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw != expected:
        raise ContractError(f"{name} must be {expected}")
    return expected


def _exact(raw: Any, expected: str, name: str) -> str:
    if raw != expected:
        raise ContractError(f"{name} must be {expected}")
    return expected


def _is_git_commit(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


def _git_commit(raw: Any, name: str) -> str:
    if not _is_git_commit(raw):
        raise ContractError(f"{name} must be a full lowercase Git commit")
    return raw


def _require_tracked_clean(path: Path, label: str) -> None:
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        completed = subprocess.run(
            ["git", *arguments],
            cwd=path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if completed.returncode == 1:
            raise ContractError(f"{label} checkout has tracked modifications")
        if completed.returncode != 0:
            raise ContractError(
                completed.stderr.strip() or f"cannot verify {label} checkout"
            )
