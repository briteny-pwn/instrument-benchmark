import io
import json

import pytest
from test_source_routed_pipeline import (
    AGENT_ENVIRONMENT,
    FakeAgentRunner,
    FakeEvaluatorRunner,
    FakeTaskRunner,
    _fixture,
)

from instrument_benchmark.orchestrator import run_agent_benchmark
from instrument_benchmark.progress import ProgressReporter
from instrument_benchmark.suite import load_suite_config, run_suite
from instrument_benchmark.task_environment import TaskEnvironmentError
from instrument_benchmark.task_environment_status import (
    EnvironmentDiagnostic,
    TaskEnvironmentResult,
)


@pytest.mark.parametrize("complete", [True, False])
@pytest.mark.parametrize("terminal", ["infrastructure_failure", "missing"])
def test_environment_failure_skips_scoring_and_persists_report(
    tmp_path, complete, terminal
):
    instrument, repos, config, report_path = _fixture(tmp_path)

    class Task(FakeTaskRunner):
        def finalize(self, handle):
            self.finalized = True
            if terminal == "missing":
                return None
            error_log = handle.evidence_root / "environment-errors.log"
            error_log.write_text("export denied")
            return TaskEnvironmentResult(
                "infrastructure_failure",
                (
                    EnvironmentDiagnostic(
                        "step_1",
                        "PermissionError",
                        "export denied secret",
                        (error_log,),
                    ),
                ),
            )

    task = Task()
    with ProgressReporter(stream=io.StringIO()):
        with pytest.raises(TaskEnvironmentError) as caught:
            run_agent_benchmark(
                config,
                agent="claudecode",
                workspace_root=tmp_path / "work",
                instrument_checkout=instrument,
                repository_paths=repos,
                environ=AGENT_ENVIRONMENT,
                agent_runner_factory=lambda: FakeAgentRunner(task, complete=complete),
                task_environment_runner_factory=lambda: task,
                evaluator_runner_factory=lambda: pytest.fail(
                    "must not score environment failure"
                ),
            )
    assert task.finalized
    report = json.loads(report_path.read_text())
    assert report["score"] is None
    assert report["evaluated"] is False
    assert report["status"] == "infrastructure_error"
    assert report["candidate_complete"] is complete
    assert report["candidate"]["files"]
    assert getattr(caught.value, "_instrbench_failure_report") == report
    assert "secret" not in report_path.read_text()
    if terminal != "missing":
        assert report["task_environment"]["status"] == "infrastructure_failure"
        assert any(
            "step_1" in item["step"]
            and "PermissionError" in item["error"]
            and item["logs"]
            for item in report["diagnostics"]
        )


def test_candidate_incomplete_environment_still_allows_partial_score(tmp_path):
    instrument, repos, config, _ = _fixture(tmp_path)

    class Task(FakeTaskRunner):
        def finalize(self, handle):
            self.finalized = True
            return TaskEnvironmentResult("candidate_incomplete")

    task, evaluator = Task(), FakeEvaluatorRunner()
    with ProgressReporter(stream=io.StringIO()):
        result = run_agent_benchmark(
            config,
            agent="claudecode",
            workspace_root=tmp_path / "work",
            instrument_checkout=instrument,
            repository_paths=repos,
            environ=AGENT_ENVIRONMENT,
            agent_runner_factory=lambda: FakeAgentRunner(task, complete=False),
            task_environment_runner_factory=lambda: task,
            evaluator_runner_factory=lambda: evaluator,
        )
    assert result["score"] == 40
    assert result["task_environment"]["status"] == "candidate_incomplete"


def test_suite_preserves_failure_report_and_has_no_mean_without_scored_runs(tmp_path):
    instrument, repos, config, _ = _fixture(tmp_path)
    suite = tmp_path / "suite.yaml"
    suite.write_text(
        "suite_id: test\nagent: claudecode\nruns: [run.yaml]\nresult_path: reports/suite.json\n"
    )

    def run(*args, **kwargs):
        exc = TaskEnvironmentError("export denied")
        exc._instrbench_failure_report = {
            "task_environment": {"status": "infrastructure_failure"},
            "candidate": {"files": ["step_1/result.stl"]},
            "candidate_available": True,
            "candidate_complete": False,
        }
        raise exc

    with ProgressReporter(stream=io.StringIO()):
        result = run_suite(
            load_suite_config(suite, repos),
            instrument_checkout=instrument,
            repository_paths=repos,
            benchmark_runner=run,
        )
    assert result.has_infrastructure_failures
    assert result.report["summary"]["mean_score"] is None
    assert result.report["summary"]["evaluated"] == 0
    assert (
        result.report["runs"][0]["task_environment"]["status"]
        == "infrastructure_failure"
    )
    assert result.report["runs"][0]["candidate"]["files"]


def test_environment_monitor_is_forwarded_to_agent_and_failure_survives_cleanup(
    tmp_path,
):
    instrument, repos, config, report_path = _fixture(tmp_path)
    error = TaskEnvironmentError(
        "live export denied",
        diagnostic=EnvironmentDiagnostic("step_2", "OSError", "live export denied"),
    )

    class Task(FakeTaskRunner):
        def check_health(self, handle):
            raise error

        def finalize(self, handle):
            self.finalized = True
            raise RuntimeError("secondary cleanup failure")

    class Agent:
        def run(self, **kwargs):
            kwargs["on_poll"]()

    task = Task()
    with ProgressReporter(stream=io.StringIO()):
        with pytest.raises(TaskEnvironmentError) as caught:
            run_agent_benchmark(
                config,
                agent="claudecode",
                workspace_root=tmp_path / "work",
                instrument_checkout=instrument,
                repository_paths=repos,
                environ=AGENT_ENVIRONMENT,
                agent_runner_factory=Agent,
                task_environment_runner_factory=lambda: task,
                evaluator_runner_factory=lambda: pytest.fail("must not score"),
            )
    assert caught.value is error
    assert task.finalized
    assert "secondary cleanup failure" in " ".join(error.__notes__)
    report = json.loads(report_path.read_text())
    assert report["score"] is None
    assert any("step_2" in item["step"] for item in report["diagnostics"])
