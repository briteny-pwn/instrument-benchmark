from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from instrument_benchmark import cli  # noqa: E402
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
