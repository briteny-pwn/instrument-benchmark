from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from .environment import RepositoryPaths


class ContractError(ValueError):
    """A source-routed benchmark contract is invalid."""


@dataclass(frozen=True)
class RunConfig:
    run_id: str
    source_id: str
    instances_repo_path: Path
    instance_id: str
    evaluator_repo_path: Path
    report_path: Path


def load_run_config(path: Path, repository_paths: RepositoryPaths) -> RunConfig:
    config_path = path.resolve()
    value = load_yaml_mapping(config_path)
    required = {"run_id", "source_id", "instance_id", "report_path"}
    if set(value) != required:
        raise ContractError("run config fields do not match")

    instances_repo_path = repository_paths.instances_repo_path.resolve()
    evaluator_repo_path = repository_paths.evaluator_repo_path.resolve()
    if not instances_repo_path.is_dir() or not evaluator_repo_path.is_dir():
        raise ContractError("instance/evaluator repository path must be a directory")

    return RunConfig(
        run_id=_identifier(value["run_id"], "run_id"),
        source_id=_identifier(value["source_id"], "source_id"),
        instances_repo_path=instances_repo_path,
        instance_id=_identifier(value["instance_id"], "instance_id"),
        evaluator_repo_path=evaluator_repo_path,
        report_path=_resolve(config_path.parent, value["report_path"]),
    )


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ContractError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{path} must contain a mapping")
    return value


def validate_visible_hashes(instance_root: Path, manifest: dict[str, Any]) -> None:
    root = instance_root.resolve()
    visible = manifest.get("visible_files")
    if not isinstance(visible, dict) or not visible:
        raise ContractError("visible_files must be a non-empty hash mapping")
    for relative, expected in visible.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ContractError("visible_files entries must be string hashes")
        path = root / relative
        try:
            metadata = path.lstat()
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ContractError(f"invalid visible file: {relative}") from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or not resolved.is_relative_to(root)
        ):
            raise ContractError(f"invalid visible file: {relative}")
        if hashlib.sha256(resolved.read_bytes()).hexdigest() != expected:
            raise ContractError(f"visible file hash mismatch: {relative}")


def dump_json(path: Path, value: Any) -> None:
    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(value, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fchmod(temporary.fileno(), 0o644)
            os.fsync(temporary.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _resolve(root: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ContractError("path values must be non-empty strings")
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _non_empty(raw: Any, name: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ContractError(f"{name} must be a non-empty string")
    return raw


def _identifier(raw: Any, name: str) -> str:
    value = _non_empty(raw, name)
    if re.fullmatch(r"[a-z][a-z0-9_-]*", value) is None:
        raise ContractError(f"{name} must be an identifier")
    return value
