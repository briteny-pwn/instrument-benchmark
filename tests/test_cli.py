from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from instrument_benchmark import cli  # noqa: E402
from instrument_benchmark.contracts import ContractError  # noqa: E402
from instrument_benchmark.environment import RepositoryPaths  # noqa: E402


def test_cli_loads_repository_paths_once_and_propagates_them(
    tmp_path: Path,
    capsys,
) -> None:
    config_path = tmp_path / "run.yaml"
    config_path.write_text("schema_version: 3\n", encoding="utf-8")
    instances = tmp_path / "instances"
    evaluator = tmp_path / "evaluator"
    instances.mkdir()
    evaluator.mkdir()
    repositories = RepositoryPaths(instances, evaluator)
    report_path = tmp_path / "report.json"

    with (
        patch.object(cli, "ROOT", tmp_path),
        patch.object(
            cli,
            "load_repository_paths",
            return_value=repositories,
        ) as environment_loader,
        patch.object(
            cli,
            "run_benchmark",
            return_value={"score": 100, "strict_pass": True},
        ) as runner,
        patch.object(
            cli,
            "load_run_config",
            return_value=SimpleNamespace(report_path=report_path),
        ) as config_loader,
    ):
        result = cli.main([str(config_path)])

    assert result == 0
    environment_loader.assert_called_once_with(tmp_path)
    runner.assert_called_once_with(
        config_path,
        instrument_checkout=tmp_path,
        repository_paths=repositories,
        allow_dirty=False,
    )
    config_loader.assert_called_once_with(config_path, repositories)
    assert json.loads(capsys.readouterr().out) == {
        "report": str(report_path),
        "score": 100,
        "strict_pass": True,
    }


def test_cli_runs_suite_and_prints_summary(tmp_path: Path, capsys) -> None:
    suite_path = tmp_path / "suite.yaml"
    instances = tmp_path / "instances"
    evaluator = tmp_path / "evaluator"
    instances.mkdir()
    evaluator.mkdir()
    repositories = RepositoryPaths(instances, evaluator)
    suite = SimpleNamespace(result_path=tmp_path / "suite-report.json")
    execution = SimpleNamespace(
        report={"summary": {"total": 2, "strict_pass": False}},
        has_infrastructure_failures=False,
    )

    with (
        patch.object(cli, "ROOT", tmp_path),
        patch.object(
            cli, "load_repository_paths", return_value=repositories
        ) as environment_loader,
        patch.object(cli, "load_suite_config", return_value=suite) as suite_loader,
        patch.object(cli, "run_suite", return_value=execution) as suite_runner,
    ):
        result = cli.main(["run", "--suite", str(suite_path)])

    assert result == 0
    environment_loader.assert_called_once_with(tmp_path)
    suite_loader.assert_called_once_with(suite_path, repositories)
    suite_runner.assert_called_once_with(
        suite,
        instrument_checkout=tmp_path,
        repository_paths=repositories,
        allow_dirty=False,
    )
    assert json.loads(capsys.readouterr().out) == {
        "report": str(suite.result_path),
        "summary": execution.report["summary"],
    }


def test_cli_run_config_propagates_allow_dirty(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "run.yaml"
    instances = tmp_path / "instances"
    evaluator = tmp_path / "evaluator"
    instances.mkdir()
    evaluator.mkdir()
    repositories = RepositoryPaths(instances, evaluator)
    report_path = tmp_path / "report.json"

    with (
        patch.object(cli, "ROOT", tmp_path),
        patch.object(cli, "load_repository_paths", return_value=repositories),
        patch.object(
            cli, "run_benchmark", return_value={"score": 50, "strict_pass": False}
        ) as runner,
        patch.object(
            cli,
            "load_run_config",
            return_value=SimpleNamespace(report_path=report_path),
        ),
    ):
        result = cli.main(["run", "--config", str(config_path), "--allow-dirty"])

    assert result == 0
    runner.assert_called_once_with(
        config_path,
        instrument_checkout=tmp_path,
        repository_paths=repositories,
        allow_dirty=True,
    )
    assert json.loads(capsys.readouterr().out) == {
        "report": str(report_path),
        "score": 50,
        "strict_pass": False,
    }


def test_cli_returns_contract_error_status(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "run.yaml"

    with (
        patch.object(cli, "ROOT", tmp_path),
        patch.object(
            cli, "load_repository_paths", side_effect=ContractError("bad config")
        ),
    ):
        result = cli.main(["run", "--config", str(config_path)])

    assert result == 2
    assert capsys.readouterr().err == "invalid benchmark contract: bad config\n"


def test_cli_returns_infrastructure_error_status_for_single_run(
    tmp_path: Path, capsys
) -> None:
    config_path = tmp_path / "run.yaml"
    repositories = RepositoryPaths(tmp_path / "instances", tmp_path / "evaluator")

    with (
        patch.object(cli, "ROOT", tmp_path),
        patch.object(cli, "load_repository_paths", return_value=repositories),
        patch.object(cli, "run_benchmark", side_effect=RuntimeError("docker unavailable")),
    ):
        result = cli.main(["run", "--config", str(config_path)])

    assert result == 3
    assert capsys.readouterr().err == (
        "benchmark infrastructure failure: docker unavailable\n"
    )


def test_cli_returns_infrastructure_status_after_suite_summary(
    tmp_path: Path, capsys
) -> None:
    suite_path = tmp_path / "suite.yaml"
    repositories = RepositoryPaths(tmp_path / "instances", tmp_path / "evaluator")
    suite = SimpleNamespace(result_path=tmp_path / "suite-report.json")
    execution = SimpleNamespace(
        report={"summary": {"total": 2, "infrastructure_failed": 1}},
        has_infrastructure_failures=True,
    )

    with (
        patch.object(cli, "ROOT", tmp_path),
        patch.object(cli, "load_repository_paths", return_value=repositories),
        patch.object(cli, "load_suite_config", return_value=suite),
        patch.object(cli, "run_suite", return_value=execution),
    ):
        result = cli.main(["run", "--suite", str(suite_path)])

    assert result == 3
    assert json.loads(capsys.readouterr().out) == {
        "report": str(suite.result_path),
        "summary": execution.report["summary"],
    }


@pytest.mark.parametrize(
    "argv",
    [
        ["run"],
        ["run", "--config", "run.yaml", "--suite", "suite.yaml"],
    ],
)
def test_cli_rejects_missing_or_ambiguous_run_target(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(argv)

    assert exc_info.value.code == 2
