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


def validate_evaluator_report(value: Any) -> dict[str, Any]:
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
    }
    missing = sorted(required - set(value))
    if missing:
        raise ContractError(f"evaluator report missing: {', '.join(missing)}")
    if value["schema_version"] != 1:
        raise ContractError("unsupported report schema_version")
    if isinstance(value["score"], bool) or not 0 <= float(value["score"]) <= 100:
        raise ContractError("report score must be between 0 and 100")
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

