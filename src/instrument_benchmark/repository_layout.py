from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .contracts import ContractError


ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True)
class ResolvedLeaf:
    source_id: str
    leaf_id: str
    root: Path
    manifest_path: Path
    source_manifest_path: Path
    manifest: dict[str, Any]
    source_manifest: dict[str, Any]


def resolve_instance_leaf(
    checkout: Path, source_id: str, instance_id: str
) -> ResolvedLeaf:
    return _resolve_registered_leaf(
        checkout,
        source_id,
        instance_id,
        registry_key="instances",
        manifest_name="instance.yaml",
        identity_key="instance_id",
    )


def resolve_evaluator_leaf(
    checkout: Path, source_id: str, evaluator_id: str
) -> ResolvedLeaf:
    return _resolve_registered_leaf(
        checkout,
        source_id,
        evaluator_id,
        registry_key="evaluators",
        manifest_name="evaluator.yaml",
        identity_key="evaluator_id",
    )


def _load_mapping(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"{label} is missing or is not a regular file")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ContractError(f"cannot load {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must contain a mapping")
    return value


def _require_id(value: str, label: str) -> None:
    if not isinstance(value, str) or ID_PATTERN.fullmatch(value) is None:
        raise ContractError(f"invalid {label}")


def _resolve_registered_leaf(
    checkout: Path,
    source_id: str,
    leaf_id: str,
    *,
    registry_key: str,
    manifest_name: str,
    identity_key: str,
) -> ResolvedLeaf:
    _require_id(source_id, "source_id")
    _require_id(leaf_id, identity_key)
    checkout = checkout.resolve(strict=True)
    sources_path = checkout / "sources"
    if sources_path.is_symlink() or not sources_path.is_dir():
        raise ContractError("sources directory is missing or is a symlink")
    if (checkout / manifest_name).exists() or any(
        checkout.glob(f"*/{manifest_name}")
    ):
        raise ContractError("legacy flat leaf layout is forbidden")
    if manifest_name == "evaluator.yaml" and (checkout / "evaluators").exists():
        raise ContractError("legacy evaluators directory is forbidden")
    source_path = sources_path / source_id
    if source_path.is_symlink() or not source_path.is_dir():
        raise ContractError("registered source directory is missing or is a symlink")
    source_root = source_path.resolve(strict=True)
    if not source_root.is_relative_to(sources_path.resolve(strict=True)):
        raise ContractError("source path escapes sources directory")
    source_manifest_path = source_root / "source.yaml"
    source = _load_mapping(source_manifest_path, "source manifest")
    if set(source) != {
        "schema_version",
        "source_id",
        "display_name",
        "description",
        registry_key,
    }:
        raise ContractError("source manifest fields are invalid")
    if source["schema_version"] != 1 or source["source_id"] != source_id:
        raise ContractError("source manifest identity is invalid")
    if not all(
        isinstance(source[name], str) and bool(source[name].strip())
        for name in ("display_name", "description")
    ):
        raise ContractError("source manifest text fields are invalid")
    registered = source[registry_key]
    if (
        not isinstance(registered, list)
        or not registered
        or any(
            not isinstance(item, str) or ID_PATTERN.fullmatch(item) is None
            for item in registered
        )
        or registered != sorted(set(registered))
    ):
        raise ContractError("source registry must be non-empty, unique, and sorted")
    actual: list[str] = []
    for child in source_root.iterdir():
        manifest_path = child / manifest_name
        if child.is_symlink() and manifest_path.exists():
            raise ContractError("leaf symlinks are forbidden")
        if manifest_path.is_symlink():
            raise ContractError("leaf manifest symlinks are forbidden")
        if child.is_dir() and manifest_path.is_file():
            actual.append(child.name)
    if registered != sorted(actual):
        raise ContractError("source registry and leaf directories differ")
    leaf_path = source_root / leaf_id
    if leaf_path.is_symlink() or not leaf_path.is_dir():
        raise ContractError("registered leaf is missing or is a symlink")
    leaf_root = leaf_path.resolve(strict=True)
    if not leaf_root.is_relative_to(source_root):
        raise ContractError("leaf path escapes source directory")
    manifest_path = leaf_root / manifest_name
    manifest = _load_mapping(manifest_path, "leaf manifest")
    if (
        manifest.get("schema_version") != 2
        or manifest.get("source_id") != source_id
        or manifest.get(identity_key) != leaf_id
    ):
        raise ContractError("leaf manifest identity is invalid")
    return ResolvedLeaf(
        source_id=source_id,
        leaf_id=leaf_id,
        root=leaf_root,
        manifest_path=manifest_path,
        source_manifest_path=source_manifest_path,
        manifest=manifest,
        source_manifest=source,
    )
