from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from instrument_benchmark.contracts import ContractError, load_run_config  # noqa: E402
from instrument_benchmark.environment import RepositoryPaths  # noqa: E402


def _repositories(tmp_path: Path) -> RepositoryPaths:
    instances = tmp_path / "instances"
    evaluator = tmp_path / "evaluator"
    instances.mkdir()
    evaluator.mkdir()
    return RepositoryPaths(
        instances_repo_path=instances,
        evaluator_repo_path=evaluator,
    )


def _config_value(candidate_path: str, **updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 3,
        "run_id": "run-v3",
        "source_id": "pyvisa",
        "instance_id": "instance-v1",
        "evaluator_id": "evaluator-v1",
        "candidate_path": candidate_path,
        "report_path": "reports/result.json",
        "timeout_seconds": 30,
        "max_output_bytes": 1024,
        "repeated_worlds": 2,
        "repeated_base_seed": 100,
        "container_protocol_version": 1,
        "image_mode": "locked",
    }
    value.update(updates)
    return value


def _write_config(tmp_path: Path, value: dict[str, object]) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    path = config_dir / "run.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def test_relative_candidate_resolves_from_evaluator_repository(tmp_path: Path) -> None:
    repositories = _repositories(tmp_path)
    relative = Path("sources/pyvisa/evaluator-v1/reference/solution.py")
    candidate = repositories.evaluator_repo_path / relative
    candidate.parent.mkdir(parents=True)
    candidate.write_text("pass\n", encoding="utf-8")
    config_path = _write_config(tmp_path, _config_value(relative.as_posix()))

    loaded = load_run_config(config_path, repositories)

    assert loaded.schema_version == 3
    assert loaded.instances_repo_path == repositories.instances_repo_path
    assert loaded.evaluator_repo_path == repositories.evaluator_repo_path
    assert loaded.candidate_path == candidate.resolve()
    assert loaded.report_path == (config_path.parent / "reports/result.json").resolve()


def test_absolute_external_candidate_remains_supported(tmp_path: Path) -> None:
    repositories = _repositories(tmp_path)
    candidate = tmp_path / "submission" / "solution.py"
    candidate.parent.mkdir()
    candidate.write_text("pass\n", encoding="utf-8")
    config_path = _write_config(tmp_path, _config_value(str(candidate)))

    loaded = load_run_config(config_path, repositories)

    assert loaded.candidate_path == candidate.resolve()


def test_relative_candidate_cannot_escape_evaluator_repository(tmp_path: Path) -> None:
    repositories = _repositories(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("pass\n", encoding="utf-8")
    config_path = _write_config(tmp_path, _config_value("../outside.py"))

    with pytest.raises(ContractError, match="candidate_path.*evaluator repository"):
        load_run_config(config_path, repositories)


def test_relative_candidate_symlink_cannot_escape_evaluator_repository(
    tmp_path: Path,
) -> None:
    repositories = _repositories(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("pass\n", encoding="utf-8")
    candidate = repositories.evaluator_repo_path / "solution.py"
    candidate.symlink_to(outside)
    config_path = _write_config(tmp_path, _config_value("solution.py"))

    with pytest.raises(ContractError, match="candidate_path.*evaluator repository"):
        load_run_config(config_path, repositories)


def test_schema_version_two_is_rejected(tmp_path: Path) -> None:
    repositories = _repositories(tmp_path)
    candidate = repositories.evaluator_repo_path / "solution.py"
    candidate.write_text("pass\n", encoding="utf-8")
    config_path = _write_config(
        tmp_path,
        _config_value("solution.py", schema_version=2),
    )

    with pytest.raises(ContractError, match="unsupported run config schema_version"):
        load_run_config(config_path, repositories)


@pytest.mark.parametrize("legacy_key", ["instance_checkout", "evaluator_checkout"])
def test_schema_version_three_rejects_legacy_checkout_keys(
    tmp_path: Path,
    legacy_key: str,
) -> None:
    repositories = _repositories(tmp_path)
    candidate = repositories.evaluator_repo_path / "solution.py"
    candidate.write_text("pass\n", encoding="utf-8")
    config_path = _write_config(
        tmp_path,
        _config_value("solution.py", **{legacy_key: "/legacy"}),
    )

    with pytest.raises(
        ContractError,
        match="run config fields do not match schema version 3",
    ):
        load_run_config(config_path, repositories)
