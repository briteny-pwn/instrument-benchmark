from __future__ import annotations

import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import ContractError


@dataclass(frozen=True)
class CandidateContract:
    producer: str
    files: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.producer not in {"agent", "task_environment"}:
            raise ContractError("candidate producer is invalid")
        if not self.files or self.files != tuple(sorted(set(self.files))):
            raise ContractError("candidate files must be non-empty, unique, and sorted")
        for value in self.files:
            _relative_file(value)

    @classmethod
    def from_source_manifest(cls, source: Mapping[str, Any]) -> "CandidateContract":
        value = source.get("candidate")
        if not isinstance(value, Mapping):
            raise ContractError("source candidate contract is missing")
        producer = value.get("producer")
        if producer == "agent" and set(value) == {"producer", "files"}:
            files = _string_list(value["files"], "candidate.files")
        elif producer == "task_environment" and set(value) == {
            "producer",
            "groups",
            "files_per_group",
        }:
            groups = _string_list(value["groups"], "candidate.groups")
            per_group = _string_list(
                value["files_per_group"], "candidate.files_per_group"
            )
            files = tuple(
                sorted(f"{group}/{relative}" for group in groups for relative in per_group)
            )
        else:
            raise ContractError("source candidate contract is invalid")
        return cls(str(producer), files)


@dataclass(frozen=True)
class CandidateInventory:
    root: Path
    files: tuple[str, ...]
    missing_files: tuple[str, ...]
    invalid_files: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing_files and not self.invalid_files

    def to_request_fields(self) -> dict[str, object]:
        return {
            "candidate_root": str(self.root),
            "candidate_files": list(self.files),
            "missing_candidate_files": list(self.missing_files),
            "invalid_candidate_files": list(self.invalid_files),
        }


def inventory_candidate(root: Path, contract: CandidateContract) -> CandidateInventory:
    candidate_root = root.resolve()
    candidate_root.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    missing: list[str] = []
    invalid: list[str] = []
    for relative in contract.files:
        path = candidate_root / relative
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            missing.append(relative)
            continue
        except OSError:
            invalid.append(relative)
            continue
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            invalid.append(relative)
            continue
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or not resolved.is_relative_to(candidate_root)
        ):
            invalid.append(relative)
        else:
            files.append(relative)
    return CandidateInventory(
        candidate_root,
        tuple(files),
        tuple(missing),
        tuple(invalid),
    )


def _string_list(raw: object, name: str) -> tuple[str, ...]:
    if (
        not isinstance(raw, list)
        or not raw
        or any(not isinstance(value, str) for value in raw)
        or len(raw) != len(set(raw))
    ):
        raise ContractError(f"{name} must be a non-empty sorted unique string list")
    return tuple(raw)


def _relative_file(value: str) -> None:
    if not isinstance(value, str):
        raise ContractError(f"invalid candidate file path: {value}")
    path = Path(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or value.endswith("/")
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ContractError(f"invalid candidate file path: {value}")
