from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ContractError(ValueError):
    """A distributed repository or run contract is invalid."""


@dataclass(frozen=True)
class RunConfig:
    schema_version: int
    run_id: str
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
    if not isinstance(value, dict) or set(value) != required:
        raise ContractError("run config fields do not match schema version 1")
    if value["schema_version"] != 1:
        raise ContractError("unsupported run config schema_version")
    root = path.parent
    instance = _resolve(root, value["instance_checkout"])
    evaluator = _resolve(root, value["evaluator_checkout"])
    candidate = _resolve(root, value["candidate_path"])
    report = _resolve(root, value["report_path"], must_exist=False)
    if not instance.is_dir() or not evaluator.is_dir():
        raise ContractError("instance/evaluator checkout must be a directory")
    if not candidate.is_file():
        raise ContractError("candidate_path must be a file")
    return RunConfig(
        schema_version=1,
        run_id=_non_empty(value["run_id"], "run_id"),
        instance_checkout=instance,
        instance_id=_non_empty(value["instance_id"], "instance_id"),
        evaluator_checkout=evaluator,
        evaluator_id=_non_empty(value["evaluator_id"], "evaluator_id"),
        candidate_path=candidate,
        report_path=report,
        timeout_seconds=_positive_number(value["timeout_seconds"], "timeout_seconds"),
        max_output_bytes=_positive_int(value["max_output_bytes"], "max_output_bytes"),
        repeated_worlds=_positive_int(value["repeated_worlds"], "repeated_worlds"),
        repeated_base_seed=_positive_int(
            value["repeated_base_seed"], "repeated_base_seed"
        ),
        container_protocol_version=_positive_int(
            value["container_protocol_version"], "container_protocol_version"
        ),
        image_mode=_exact(value["image_mode"], "locked", "image_mode"),
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
    path: Path, *, allow_dirty: bool = False
) -> RepositoryProvenance:
    root = path.resolve()
    if _git(root, "rev-parse", "--show-toplevel") != str(root):
        raise ContractError(f"not a repository root: {root}")
    status = _git(root, "status", "--porcelain")
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
    instance: dict[str, Any], evaluator: dict[str, Any]
) -> None:
    instance_id = instance.get("instance_id")
    evaluator_contract = instance.get("evaluator")
    if not isinstance(evaluator_contract, dict):
        raise ContractError("instance evaluator contract is missing")
    if evaluator_contract.get("id") != evaluator.get("evaluator_id"):
        raise ContractError("evaluator id mismatch")
    if evaluator_contract.get("protocol_version") != evaluator.get(
        "protocol_version"
    ):
        raise ContractError("evaluator protocol mismatch")
    if instance_id not in evaluator.get("supported_instances", []):
        raise ContractError("instance is not supported by evaluator")
    container = instance.get("container")
    if not isinstance(container, dict):
        raise ContractError("instance container contract is missing")
    protocol = container.get("protocol_version")
    if protocol != evaluator.get("container_protocol_version"):
        raise ContractError("container protocol mismatch")
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


def validate_evaluator_report(
    value: Any,
    evaluator_id: str = "pyvisa_dut_validation_v1",
    *,
    expected_run_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("evaluator report must be an object")
    required = {
        "schema_version",
        "status",
        "strict_pass",
        "score",
        "dimensions",
        "strict_gates",
        "evidence_confidence",
        "worlds",
        "infrastructure_valid",
        "retry_eligible",
    }
    missing = sorted(required - set(value))
    if missing:
        raise ContractError(f"evaluator report missing: {', '.join(missing)}")
    expected_schema = {
        "pyvisa_dut_validation_v1": 1,
        "pyvisa_dut_validation_v2": 2,
    }.get(evaluator_id)
    if expected_schema is None:
        raise ContractError("unsupported evaluator report id")
    if value["schema_version"] != expected_schema:
        raise ContractError("report schema_version does not match evaluator")
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
        _validate_v2_report(
            value,
            worlds,
            evaluator_id,
            expected_run_id=expected_run_id,
        )
        return value
    _validate_v1_worlds(worlds)
    return value


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


def _validate_v2_report(
    report: dict[str, Any],
    worlds: list[Any],
    evaluator_id: str,
    *,
    expected_run_id: str | None,
) -> None:
    if (
        not isinstance(report.get("infrastructure_valid"), bool)
        or not isinstance(report.get("retry_eligible"), bool)
    ):
        raise ContractError("v2 aggregate infrastructure status is invalid")
    evaluator = report.get("evaluator")
    if (
        not isinstance(evaluator, dict)
        or evaluator.get("id") != evaluator_id
        or evaluator.get("protocol_version") != 1
        or not isinstance(evaluator.get("run_id"), str)
        or not evaluator["run_id"]
    ):
        raise ContractError("v2 report evaluator identity is invalid")
    if expected_run_id is not None and evaluator["run_id"] != expected_run_id:
        raise ContractError("v2 report run ID does not match this run")
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
        if (
            not events
            or events[0]["kind"] != "lifecycle.start"
            or events[-1]["kind"] != "lifecycle.finalized"
            or not isinstance(value["pre_cleanup_snapshot"], dict)
            or not isinstance(value["post_cleanup_snapshot"], dict)
            or value["post_cleanup_snapshot"].get("safe") is not True
        ):
            raise ContractError(
                f"world {index} sim journal lifecycle is incomplete"
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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


def _positive_number(raw: Any, name: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw <= 0:
        raise ContractError(f"{name} must be positive")
    return float(raw)


def _positive_int(raw: Any, name: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ContractError(f"{name} must be a positive integer")
    return raw


def _exact(raw: Any, expected: str, name: str) -> str:
    if raw != expected:
        raise ContractError(f"{name} must be {expected}")
    return expected
