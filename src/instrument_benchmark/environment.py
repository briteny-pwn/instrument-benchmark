from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from .contracts import ContractError


INSTANCES_REPO_PATH = "INSTANCES_REPO_PATH"
EVALUATOR_REPO_PATH = "EVALUATOR_REPO_PATH"
_REPOSITORY_VARIABLES = (INSTANCES_REPO_PATH, EVALUATOR_REPO_PATH)


@dataclass(frozen=True)
class RepositoryPaths:
    instances_repo_path: Path
    evaluator_repo_path: Path


def read_repository_path_values(
    instrument_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    process = os.environ if environ is None else environ
    dotenv_path = instrument_root.resolve() / ".env"
    try:
        file_values = dotenv_values(dotenv_path=dotenv_path)
    except OSError as exc:
        raise ContractError(f"cannot load repository environment: {exc}") from exc
    return tuple(
        _required_value(name, process, file_values)
        for name in _REPOSITORY_VARIABLES
    )


def load_repository_paths(
    instrument_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> RepositoryPaths:
    instances, evaluator = read_repository_path_values(
        instrument_root,
        environ=environ,
    )
    return RepositoryPaths(
        instances_repo_path=_repository_directory(INSTANCES_REPO_PATH, instances),
        evaluator_repo_path=_repository_directory(EVALUATOR_REPO_PATH, evaluator),
    )


def _required_value(
    name: str,
    process: Mapping[str, str],
    file_values: Mapping[str, str | None],
) -> str:
    if name in process:
        value = process[name]
    else:
        value = file_values.get(name)
    if value is None:
        raise ContractError(f"{name} is required")
    if not value.strip():
        raise ContractError(f"{name} must not be blank")
    return value


def _repository_directory(name: str, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ContractError(f"{name} must be an absolute path")
    resolved = path.resolve()
    if not resolved.is_dir():
        raise ContractError(f"{name} must name an existing directory")
    return resolved
