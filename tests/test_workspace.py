from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from instrument_benchmark.contracts import ContractError
from instrument_benchmark.workspace import candidate_sha256, prepare_workspace


def _manifest(filename: object = "answer.json") -> dict[str, object]:
    return {
        "visible_files": {
            "prompt.md": "unused-in-this-unit-test",
            "docs/api.md": "unused-in-this-unit-test",
            f"starter/{filename}": "unused-in-this-unit-test",
        },
        "submission": {"filename": filename},
    }


def _task(tmp_path: Path, filename: str = "answer.json") -> Path:
    task = tmp_path / "task"
    (task / "starter").mkdir(parents=True)
    (task / "docs").mkdir()
    (task / "prompt.md").write_text(
        f"Write the final submission to `{filename}`.\n", encoding="utf-8"
    )
    (task / "docs" / "api.md").write_text("public api\n", encoding="utf-8")
    (task / "starter" / filename).write_text("{}\n", encoding="utf-8")
    (task / "private.txt").write_text("must not be copied\n", encoding="utf-8")
    return task


def test_prepares_unique_workspace_from_manifest_visible_files(tmp_path: Path) -> None:
    task = _task(tmp_path)
    destination = tmp_path / "runs"

    prepared = prepare_workspace(task, _manifest(), destination)
    second = prepare_workspace(task, _manifest(), destination)

    assert prepared.root.parent == destination.resolve()
    assert prepared.root != second.root
    assert prepared.prompt == "Write the final submission to `answer.json`.\n"
    assert prepared.candidate_path == prepared.root / "answer.json"
    assert (prepared.root / "answer.json").read_text() == "{}\n"
    assert (prepared.root / "docs" / "api.md").read_text() == "public api\n"
    assert (prepared.root / "prompt.md").is_file()
    assert not (prepared.root / "starter").exists()
    assert not (prepared.root / "private.txt").exists()
    assert prepared.initial_candidate_sha256 == hashlib.sha256(b"{}\n").hexdigest()


def test_submission_filename_is_not_hard_coded(tmp_path: Path) -> None:
    task = _task(tmp_path, "experiment.py")

    prepared = prepare_workspace(
        task, _manifest("experiment.py"), tmp_path / "runs"
    )

    assert prepared.candidate_path.name == "experiment.py"


@pytest.mark.parametrize(
    "filename",
    [None, "", ".", "..", "/tmp/answer.json", "../answer.json", "nested/answer.json"],
)
def test_rejects_invalid_submission_filename(
    tmp_path: Path, filename: object
) -> None:
    task = _task(tmp_path)

    with pytest.raises(ContractError, match="submission.filename"):
        prepare_workspace(task, _manifest(filename), tmp_path / "runs")


def test_rejects_prompt_that_disagrees_with_submission_filename(
    tmp_path: Path,
) -> None:
    task = _task(tmp_path)
    (task / "prompt.md").write_text("Write a different file.\n", encoding="utf-8")

    with pytest.raises(ContractError, match="prompt.md.*submission.filename"):
        prepare_workspace(task, _manifest(), tmp_path / "runs")


def test_rejects_visible_source_symlink(tmp_path: Path) -> None:
    task = _task(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("secret\n", encoding="utf-8")
    (task / "docs" / "api.md").unlink()
    (task / "docs" / "api.md").symlink_to(outside)

    with pytest.raises(ContractError, match="visible file.*symlink"):
        prepare_workspace(task, _manifest(), tmp_path / "runs")


def test_rejects_workspace_destination_collisions(tmp_path: Path) -> None:
    task = _task(tmp_path)
    (task / "answer.json").write_text("collision\n", encoding="utf-8")
    manifest = _manifest()
    manifest["visible_files"]["answer.json"] = "unused-in-this-unit-test"  # type: ignore[index]

    with pytest.raises(ContractError, match="workspace destination collision"):
        prepare_workspace(task, manifest, tmp_path / "runs")


def test_candidate_hash_returns_none_for_missing_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    assert candidate_sha256(workspace / "answer.json", workspace) is None


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_candidate_hash_rejects_non_regular_or_escaping_file(
    tmp_path: Path, kind: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    candidate = workspace / "answer.json"
    if kind == "directory":
        candidate.mkdir()
    else:
        outside = tmp_path / "outside.json"
        outside.write_text("{}\n", encoding="utf-8")
        candidate.symlink_to(outside)

    with pytest.raises(ContractError, match="candidate.*regular file"):
        candidate_sha256(candidate, workspace)
