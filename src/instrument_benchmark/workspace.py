from __future__ import annotations

import hashlib
import shutil
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import ContractError


@dataclass(frozen=True)
class PreparedWorkspace:
    root: Path
    prompt: str
    candidate_path: Path
    initial_candidate_sha256: str | None


def prepare_workspace(
    instance_root: Path,
    manifest: Mapping[str, Any],
    workspace_root: Path,
) -> PreparedWorkspace:
    instance = instance_root.resolve()
    filename = _submission_filename(manifest)
    inputs = _visible_inputs(instance, manifest)
    prompt_source = instance / "prompt.md"
    if prompt_source not in {source for source, _ in inputs}:
        raise ContractError("prompt.md must be a visible file")
    try:
        prompt = prompt_source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"cannot load prompt.md: {exc}") from exc
    if filename not in prompt:
        raise ContractError("prompt.md must mention submission.filename")

    try:
        workspace_parent = workspace_root.resolve()
        workspace_parent.mkdir(parents=True, exist_ok=True)
        workspace = Path(
            tempfile.mkdtemp(prefix="run-", dir=workspace_parent)
        ).resolve()
        for source, relative_destination in inputs:
            destination = workspace / relative_destination
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    except OSError as exc:
        raise ContractError(f"cannot prepare task workspace: {exc}") from exc

    candidate = workspace / filename
    return PreparedWorkspace(
        root=workspace,
        prompt=prompt,
        candidate_path=candidate,
        initial_candidate_sha256=candidate_sha256(candidate, workspace),
    )


def candidate_sha256(candidate_path: Path, workspace: Path) -> str | None:
    try:
        metadata = candidate_path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ContractError(f"cannot inspect candidate file: {exc}") from exc

    workspace_root = workspace.resolve()
    try:
        resolved = candidate_path.resolve(strict=True)
    except OSError as exc:
        raise ContractError(f"candidate must be a regular file: {exc}") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or not resolved.is_relative_to(workspace_root)
    ):
        raise ContractError("candidate must be a regular file inside the workspace")
    try:
        return hashlib.sha256(candidate_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ContractError(f"cannot read candidate file: {exc}") from exc


def _submission_filename(manifest: Mapping[str, Any]) -> str:
    submission = manifest.get("submission")
    if not isinstance(submission, Mapping):
        raise ContractError("submission.filename is required")
    filename = submission.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        raise ContractError("submission.filename must be a non-empty string")
    path = Path(filename)
    if path.is_absolute() or len(path.parts) != 1 or path.name != filename:
        raise ContractError("submission.filename must name one relative file")
    return filename


def _visible_inputs(
    instance_root: Path, manifest: Mapping[str, Any]
) -> tuple[tuple[Path, Path], ...]:
    visible = manifest.get("visible_files")
    if not isinstance(visible, Mapping) or not visible:
        raise ContractError("visible_files must be a non-empty mapping")

    inputs: list[tuple[Path, Path]] = []
    destinations: set[Path] = set()
    for raw_relative in sorted(visible, key=str):
        if not isinstance(raw_relative, str) or not raw_relative:
            raise ContractError("visible file paths must be non-empty strings")
        relative = Path(raw_relative)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ContractError(f"invalid visible file path: {raw_relative}")
        source = instance_root / relative
        _require_regular_source(instance_root, source, raw_relative)

        if relative.parts[0] == "starter":
            if len(relative.parts) == 1:
                raise ContractError("starter must contain visible files")
            destination = Path(*relative.parts[1:])
        else:
            destination = relative
        if destination in destinations:
            raise ContractError(f"workspace destination collision: {destination}")
        destinations.add(destination)
        inputs.append((source, destination))
    return tuple(inputs)


def _require_regular_source(root: Path, source: Path, display: str) -> None:
    current = root
    for part in source.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise ContractError(f"visible file must not be a symlink: {display}")
    try:
        metadata = source.lstat()
        resolved = source.resolve(strict=True)
    except OSError as exc:
        raise ContractError(f"invalid visible file {display}: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode) or not resolved.is_relative_to(root):
        raise ContractError(f"visible file must be a regular file: {display}")
