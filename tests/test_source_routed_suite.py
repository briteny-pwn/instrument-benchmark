from __future__ import annotations

import json
from pathlib import Path

from instrument_benchmark.environment import RepositoryPaths
from instrument_benchmark.suite import load_suite_config, run_suite


def test_suite_aggregates_source_routed_candidate_results(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    evaluator = tmp_path / "evaluator"
    tasks.mkdir()
    evaluator.mkdir()
    run_path = tmp_path / "run.yaml"
    run_path.write_text(
        "run_id: run-1\n"
        "source_id: demo\n"
        "instance_id: task\n"
        "report_path: reports/run.json\n"
    )
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        "suite_id: demo\n"
        "agent: claudecode\n"
        "runs:\n  - run.yaml\n"
        "result_path: reports/suite.json\n"
    )
    repositories = RepositoryPaths(tasks, evaluator)
    config = load_suite_config(suite_path, repositories)

    def benchmark_runner(config_path: Path, **_: object) -> dict[str, object]:
        assert config_path == run_path.resolve()
        return {
            "status": "partial",
            "score": 25.0,
            "strict_pass": False,
            "candidate_available": True,
            "candidate_complete": False,
            "evaluated": True,
        }

    execution = run_suite(
        config,
        instrument_checkout=tmp_path,
        repository_paths=repositories,
        benchmark_runner=benchmark_runner,
    )

    report = execution.report
    assert report["runs"][0]["source_id"] == "demo"
    assert "evaluator_id" not in report["runs"][0]
    assert report["summary"]["complete_candidates"] == 0
    assert report["summary"]["incomplete_candidates"] == 1
    assert json.loads(config.result_path.read_text()) == report
