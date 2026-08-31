from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from instrument_benchmark.contracts import ContractError  # noqa: E402
from instrument_benchmark.environment import RepositoryPaths  # noqa: E402
from instrument_benchmark.suite import (  # noqa: E402
    SuiteExecution,
    load_suite_config,
    run_suite,
)


def _repositories(tmp_path: Path) -> RepositoryPaths:
    instances = tmp_path / "instances"
    evaluator = tmp_path / "evaluator"
    instances.mkdir()
    evaluator.mkdir()
    return RepositoryPaths(instances, evaluator)


def _run_value(candidate_path: str, **updates: object) -> dict[str, object]:
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


def _write_run(
    path: Path,
    repositories: RepositoryPaths,
    *,
    run_id: str,
    report_path: str = "reports/result.json",
) -> Path:
    candidate = repositories.evaluator_repo_path / "solution.py"
    candidate.write_text("pass\n", encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            _run_value("solution.py", run_id=run_id, report_path=report_path),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def suite_fixture(tmp_path: Path) -> tuple[RepositoryPaths, Path, Path]:
    repositories = _repositories(tmp_path)
    first = _write_run(tmp_path / "runs" / "first.yaml", repositories, run_id="first")
    second = _write_run(
        tmp_path / "runs" / "second.yaml",
        repositories,
        run_id="second",
        report_path="reports/second.json",
    )
    return repositories, first, second


def _write_suite(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def _suite_value(*runs: object, **updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "suite_id": "example",
        "runs": list(runs),
        "result_path": "results/example.json",
    }
    value.update(updates)
    return value


def loaded_suite_fixture(tmp_path: Path):
    repositories, first, second = suite_fixture(tmp_path)
    suite_path = _write_suite(
        tmp_path / "suite" / "example.yaml",
        _suite_value(str(first), str(second)),
    )
    return load_suite_config(suite_path, repositories), repositories


def test_run_suite_executes_every_entry_in_declaration_order_and_publishes(
    tmp_path: Path,
) -> None:
    suite, repositories = loaded_suite_fixture(tmp_path)
    calls: list[Path] = []

    def runner(config_path: Path, **kwargs: object) -> dict[str, object]:
        calls.append(config_path)
        return {"score": 100.0, "strict_pass": len(calls) == 1}

    execution = run_suite(
        suite,
        instrument_checkout=tmp_path,
        repository_paths=repositories,
        benchmark_runner=runner,
    )

    assert isinstance(execution, SuiteExecution)
    assert calls == [entry.config_path for entry in suite.entries]
    assert execution.report["summary"] == {
        "total": 2,
        "completed": 2,
        "infrastructure_failed": 0,
        "strict_passed": 1,
        "strict_pass": False,
    }
    assert execution.report["runs"] == [
        {
            "index": 0,
            "config_path": str(suite.entries[0].config_path),
            "run_id": "first",
            "source_id": "pyvisa",
            "instance_id": "instance-v1",
            "evaluator_id": "evaluator-v1",
            "report_path": str(suite.entries[0].config.report_path),
            "status": "completed",
            "score": 100.0,
            "strict_pass": True,
            "error": None,
        },
        {
            "index": 1,
            "config_path": str(suite.entries[1].config_path),
            "run_id": "second",
            "source_id": "pyvisa",
            "instance_id": "instance-v1",
            "evaluator_id": "evaluator-v1",
            "report_path": str(suite.entries[1].config.report_path),
            "status": "completed",
            "score": 100.0,
            "strict_pass": False,
            "error": None,
        },
    ]
    assert json.loads(suite.result_path.read_text()) == execution.report


def test_run_suite_continues_after_infrastructure_failure(
    tmp_path: Path,
) -> None:
    suite, repositories = loaded_suite_fixture(tmp_path)
    calls: list[tuple[Path, dict[str, object]]] = []

    def runner(config_path: Path, **kwargs: object) -> dict[str, object]:
        calls.append((config_path, kwargs))
        if len(calls) == 1:
            raise RuntimeError("docker unavailable")
        return {"score": 75.0, "strict_pass": True}

    execution = run_suite(
        suite,
        instrument_checkout=tmp_path,
        repository_paths=repositories,
        allow_dirty=True,
        benchmark_runner=runner,
    )

    assert [config_path for config_path, _ in calls] == [
        entry.config_path for entry in suite.entries
    ]
    for _, kwargs in calls:
        assert kwargs["instrument_checkout"] == tmp_path
        assert kwargs["repository_paths"] is repositories
        assert kwargs["allow_dirty"] is True
    first = execution.report["runs"][0]
    assert first["status"] == "infrastructure_error"
    assert first["score"] is None
    assert first["strict_pass"] is None
    assert first["error"] == "RuntimeError: docker unavailable"
    assert execution.has_infrastructure_failures is True


def test_suite_resolves_ordered_run_and_result_paths_from_its_directory(
    tmp_path: Path,
) -> None:
    repositories, first, second = suite_fixture(tmp_path)
    suite_path = tmp_path / "suite" / "example.yaml"
    suite_path.parent.mkdir()
    suite_path.write_text(
        "schema_version: 1\n"
        "suite_id: example\n"
        "runs:\n"
        f"  - ../{first.relative_to(tmp_path)}\n"
        f"  - ../{second.relative_to(tmp_path)}\n"
        "result_path: results/example.json\n",
        encoding="utf-8",
    )

    suite = load_suite_config(suite_path, repositories)

    assert suite.suite_id == "example"
    assert tuple(entry.config_path for entry in suite.entries) == (
        first.resolve(),
        second.resolve(),
    )
    assert suite.result_path == (suite_path.parent / "results/example.json").resolve()


@pytest.mark.parametrize(
    "value",
    [
        ["not", "a", "mapping"],
        _suite_value("run.yaml", extra="field"),
        {"schema_version": 1, "suite_id": "example", "runs": ["run.yaml"]},
        _suite_value("run.yaml", schema_version=0),
        _suite_value("run.yaml", schema_version=2),
        _suite_value("run.yaml", suite_id="Bad Identifier"),
        _suite_value(),
        _suite_value(runs="run.yaml"),
        _suite_value(3),
        _suite_value("run.yaml", result_path=""),
    ],
)
def test_suite_rejects_invalid_contract_shapes(tmp_path: Path, value: object) -> None:
    repositories, first, _ = suite_fixture(tmp_path)
    if isinstance(value, dict) and value.get("runs") == ["run.yaml"]:
        value["runs"] = [str(first)]
    suite_path = _write_suite(tmp_path / "suite" / "example.yaml", value)

    with pytest.raises(ContractError):
        load_suite_config(suite_path, repositories)


def test_suite_rejects_missing_run_file(tmp_path: Path) -> None:
    repositories, _, _ = suite_fixture(tmp_path)
    suite_path = _write_suite(
        tmp_path / "suite" / "example.yaml", _suite_value("missing.yaml")
    )

    with pytest.raises(ContractError):
        load_suite_config(suite_path, repositories)


@pytest.mark.parametrize(
    "value",
    [
        _suite_value("bad\0run.yaml"),
        _suite_value("run.yaml", result_path="results/bad\0result.json"),
    ],
)
def test_suite_converts_nul_path_resolution_errors_to_contract_errors(
    tmp_path: Path, value: object
) -> None:
    repositories, _, _ = suite_fixture(tmp_path)
    _write_run(tmp_path / "suite" / "run.yaml", repositories, run_id="run")
    suite_path = _write_suite(tmp_path / "suite" / "example.yaml", value)

    with pytest.raises(ContractError, match="cannot resolve suite path"):
        load_suite_config(suite_path, repositories)


def test_suite_rejects_duplicate_resolved_run_paths_including_symlink_aliases(
    tmp_path: Path,
) -> None:
    repositories, first, _ = suite_fixture(tmp_path)
    alias = tmp_path / "runs" / "alias.yaml"
    alias.symlink_to(first)
    suite_path = _write_suite(
        tmp_path / "suite" / "example.yaml",
        _suite_value(str(first), str(alias)),
    )

    with pytest.raises(ContractError, match="duplicate run path"):
        load_suite_config(suite_path, repositories)


def test_suite_rejects_duplicate_run_ids(tmp_path: Path) -> None:
    repositories, first, _ = suite_fixture(tmp_path)
    second = _write_run(tmp_path / "other" / "second.yaml", repositories, run_id="first")
    suite_path = _write_suite(
        tmp_path / "suite" / "example.yaml", _suite_value(str(first), str(second))
    )

    with pytest.raises(ContractError, match="duplicate run_id"):
        load_suite_config(suite_path, repositories)


def test_suite_rejects_duplicate_per_run_report_paths(tmp_path: Path) -> None:
    repositories, first, _ = suite_fixture(tmp_path)
    report = tmp_path / "reports" / "shared.json"
    second = _write_run(
        tmp_path / "other" / "second.yaml",
        repositories,
        run_id="second",
        report_path=str(report),
    )
    first_value = yaml.safe_load(first.read_text(encoding="utf-8"))
    first_value["report_path"] = str(report)
    first.write_text(yaml.safe_dump(first_value, sort_keys=False), encoding="utf-8")
    suite_path = _write_suite(
        tmp_path / "suite" / "example.yaml", _suite_value(str(first), str(second))
    )

    with pytest.raises(ContractError, match="duplicate run report_path"):
        load_suite_config(suite_path, repositories)


def test_suite_rejects_result_collision_with_per_run_report(tmp_path: Path) -> None:
    repositories, first, _ = suite_fixture(tmp_path)
    result = tmp_path / "suite" / "results" / "example.json"
    first_value = yaml.safe_load(first.read_text(encoding="utf-8"))
    first_value["report_path"] = str(result)
    first.write_text(yaml.safe_dump(first_value, sort_keys=False), encoding="utf-8")
    suite_path = _write_suite(
        tmp_path / "suite" / "example.yaml",
        _suite_value(str(first), result_path="results/example.json"),
    )

    with pytest.raises(ContractError, match="suite result_path collides"):
        load_suite_config(suite_path, repositories)
