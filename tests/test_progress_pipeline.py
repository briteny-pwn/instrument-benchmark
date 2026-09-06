from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from test_source_routed_pipeline import (
    AGENT_ENVIRONMENT,
    FakeAgentRunner,
    FakeEvaluatorRunner,
    FakeTaskRunner,
    _fixture,
)

from instrument_benchmark.orchestrator import run_agent_benchmark
from instrument_benchmark.progress import STAGES, ProgressReporter


def test_pipeline_emits_eight_stages_and_preserves_scoring(tmp_path: Path) -> None:
    instrument, repositories, config, report_path = _fixture(tmp_path)
    task = FakeTaskRunner()
    evaluator = FakeEvaluatorRunner()
    stream = io.StringIO()
    with ProgressReporter(stream=stream) as progress:
        result = run_agent_benchmark(
            config,
            agent="claudecode",
            workspace_root=tmp_path / "workspaces",
            instrument_checkout=instrument,
            repository_paths=repositories,
            environ=AGENT_ENVIRONMENT,
            agent_runner_factory=lambda: FakeAgentRunner(task, complete=True),
            task_environment_runner_factory=lambda: task,
            evaluator_runner_factory=lambda: evaluator,
        )
    assert result["score"] == 100
    assert result["strict_pass"] is True
    assert progress.completed == set(STAGES)
    assert len(result["diagnostics"]) == 1
    assert "exit_code=1" in result["diagnostics"][0]["error"]
    assert result == json.loads(report_path.read_text())
    assert "Agent 执行" in stream.getvalue()
    assert "建议" not in stream.getvalue()
    events = list((tmp_path / "workspaces").rglob("progress.jsonl"))
    assert len(events) == 1
    assert "stage_completed" in events[0].read_text()


def test_agent_launch_error_survives_cleanup_error(tmp_path: Path) -> None:
    instrument, repositories, config, _ = _fixture(tmp_path)
    original = RuntimeError("cannot launch agent")

    class Agent:
        def run(self, **kwargs):
            raise original

    class Task(FakeTaskRunner):
        def finalize(self, handle):
            raise OSError("container removal failed")

    with ProgressReporter(stream=io.StringIO()) as progress:
        with pytest.raises(RuntimeError) as captured:
            run_agent_benchmark(
                config,
                agent="claudecode",
                workspace_root=tmp_path / "workspaces",
                instrument_checkout=instrument,
                repository_paths=repositories,
                environ=AGENT_ENVIRONMENT,
                agent_runner_factory=Agent,
                task_environment_runner_factory=Task,
                evaluator_runner_factory=lambda: pytest.fail(
                    "no scoring after failed cleanup"
                ),
            )
    assert captured.value is original
    assert "cannot launch agent" in progress.diagnostics[0]["error"]
    assert any(
        "container removal failed" in entry["error"] for entry in progress.diagnostics
    )
    assert "Agent" in progress.diagnostics[0]["step"]


def test_evaluator_failure_keeps_observed_candidate_state_in_suite(
    tmp_path: Path,
) -> None:
    from instrument_benchmark.suite import load_suite_config, run_suite

    instrument, repositories, config, _ = _fixture(tmp_path)
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        "suite_id: example\nagent: claudecode\nruns: [run.yaml]\nresult_path: suite.json\n"
    )
    task = FakeTaskRunner()

    class Evaluator:
        def evaluate(self, **kwargs):
            raise RuntimeError("scorer crashed")

    def runner(path, **kwargs):
        return run_agent_benchmark(
            path,
            **kwargs,
            environ=AGENT_ENVIRONMENT,
            agent_runner_factory=lambda: FakeAgentRunner(task, complete=True),
            task_environment_runner_factory=lambda: task,
            evaluator_runner_factory=Evaluator,
        )

    with ProgressReporter(stream=io.StringIO()):
        result = run_suite(
            load_suite_config(suite_path, repositories),
            instrument_checkout=instrument,
            repository_paths=repositories,
            benchmark_runner=runner,
        )
    run = result.report["runs"][0]
    assert run["score"] is None and run["evaluated"] is False
    assert run["candidate_available"] is True and run["candidate_complete"] is True
    assert any("scorer crashed" in item["error"] for item in run["diagnostics"])


def test_suite_saves_partial_results_and_stops_after_interrupt(tmp_path: Path) -> None:
    from instrument_benchmark.suite import load_suite_config, run_suite

    instrument, repositories, config, _ = _fixture(tmp_path)
    second = tmp_path / "run2.yaml"
    second.write_text(
        config.read_text().replace("run-1", "run-2").replace("run.json", "run2.json")
    )
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        "suite_id: example\nagent: claudecode\nruns: [run.yaml, run2.yaml]\nresult_path: suite.json\n"
    )
    seen = []

    def runner(path, **kwargs):
        seen.append(path)
        raise KeyboardInterrupt()

    with ProgressReporter(stream=io.StringIO()):
        with pytest.raises(KeyboardInterrupt):
            run_suite(
                load_suite_config(suite_path, repositories),
                instrument_checkout=instrument,
                repository_paths=repositories,
                benchmark_runner=runner,
            )
    assert seen == [config.resolve()]
    report = json.loads((tmp_path / "suite.json").read_text())
    assert report["interrupted"] is True
    assert report["runs"][0]["status"] == "interrupted"
    assert report["summary"]["strict_pass"] is False
