from __future__ import annotations

from pathlib import Path

import pytest

from instrument_benchmark.contracts import ContractError, load_run_config
from instrument_benchmark.environment import RepositoryPaths


def _repositories(tmp_path: Path) -> RepositoryPaths:
    tasks = tmp_path / "tasks"
    evaluator = tmp_path / "evaluator"
    tasks.mkdir()
    evaluator.mkdir()
    return RepositoryPaths(tasks, evaluator)


def test_run_config_only_selects_source_instance_and_report(tmp_path: Path) -> None:
    config = tmp_path / "run.yaml"
    config.write_text(
        "run_id: run-1\n"
        "source_id: openfibsem\n"
        "instance_id: fibsem_liftout_v1\n"
        "report_path: reports/run.json\n"
    )

    loaded = load_run_config(config, _repositories(tmp_path))

    assert loaded.run_id == "run-1"
    assert loaded.source_id == "openfibsem"
    assert loaded.instance_id == "fibsem_liftout_v1"
    assert loaded.report_path == (tmp_path / "reports/run.json").resolve()
    assert not hasattr(loaded, "evaluator_id")
    assert not hasattr(loaded, "candidate_path")


@pytest.mark.parametrize("obsolete", ["evaluator_id", "candidate_path"])
def test_run_config_rejects_obsolete_routing_fields(
    tmp_path: Path, obsolete: str
) -> None:
    config = tmp_path / "run.yaml"
    config.write_text(
        "run_id: run-1\n"
        "source_id: openfibsem\n"
        "instance_id: fibsem_liftout_v1\n"
        "report_path: reports/run.json\n"
        f"{obsolete}: legacy\n"
    )

    with pytest.raises(ContractError, match="fields do not match"):
        load_run_config(config, _repositories(tmp_path))


def test_run_config_rejects_run_id_path_traversal(tmp_path: Path) -> None:
    config = tmp_path / "run.yaml"
    config.write_text(
        "run_id: ../../escape\n"
        "source_id: openfibsem\n"
        "instance_id: fibsem_liftout_v1\n"
        "report_path: reports/run.json\n"
    )

    with pytest.raises(ContractError, match="run_id must be an identifier"):
        load_run_config(config, _repositories(tmp_path))
