from __future__ import annotations

import sys
from pathlib import Path

import pytest

from instrument_benchmark.agent import AgentExecution
from instrument_benchmark.environment import RepositoryPaths
from instrument_benchmark.orchestrator import run_agent_benchmark
from instrument_benchmark.task_environment import TaskEnvironmentHandle


ROOT = Path(__file__).resolve().parents[1]
SUITE_ROOT = ROOT.parent
TASKS = SUITE_ROOT / "instrument-benchmark-instances"
EVALUATOR = SUITE_ROOT / "instrument-benchmark-evaluator"


class ExportingTaskEnvironment:
    def __init__(self) -> None:
        self.finalized = False

    def start(self, **kwargs: object) -> TaskEnvironmentHandle:
        if str(TASKS) not in sys.path:
            sys.path.insert(0, str(TASKS))
        from sources.openfibsem.task_environment.checkpoint_exporter import (
            CheckpointExporter,
        )
        from sources.openfibsem.task_environment.journal import EventJournal
        from sources.openfibsem.task_environment.models import ScenarioSpec
        from sources.openfibsem.task_environment.service import FibsemService
        from sources.openfibsem.task_environment.tests.fakes import RecordingBackend

        run_root = Path(kwargs["run_root"])
        candidate = run_root / "candidate"
        evidence = run_root / "task-evidence"
        scenario = ScenarioSpec.from_path(
            TASKS / "sources/openfibsem/fibsem_liftout_v1/scenarios/nominal.json"
        )
        service = FibsemService(
            RecordingBackend(),
            scenario,
            EventJournal("smoke", "nominal"),
            CheckpointExporter(candidate),
            evidence_root=evidence,
        )
        for step in ("step_1", "step_2", "step_3", "step_4"):
            service.checkpoint(step)
        service.finalize(outcome="completed", forced=False)
        return TaskEnvironmentHandle(
            candidate,
            evidence,
            {"FIBSEM_IAB_SOCKET": str(run_root / "unused.sock")},
        )

    def finalize(self, handle: TaskEnvironmentHandle) -> None:
        assert handle.candidate_root.is_dir()
        self.finalized = True


class NoOpAgent:
    def run(self, **kwargs: object) -> AgentExecution:
        artifacts = Path(kwargs["artifacts_root"])
        artifacts.mkdir(parents=True)
        stdout = artifacts / "agent-output.jsonl"
        stderr = artifacts / "agent-stderr.log"
        stdout.write_text("")
        stderr.write_text("")
        return AgentExecution(
            agent="claudecode",
            model="smoke-model",
            isolation="trusted_host",
            status="completed",
            exit_code=0,
            duration_seconds=0.0,
            workspace=Path(kwargs["workspace"]),
            stdout_path=stdout,
            stderr_path=stderr,
            command=("claude", "-p"),
        )


@pytest.mark.smoke
def test_three_repo_source_routed_artifact_smoke(tmp_path: Path) -> None:
    if not TASKS.is_dir() or not EVALUATOR.is_dir():
        pytest.skip("sibling task/evaluator repositories are unavailable")
    config = tmp_path / "run.yaml"
    report_path = tmp_path / "report.json"
    config.write_text(
        "run_id: three-repo-smoke\n"
        "source_id: openfibsem\n"
        "instance_id: fibsem_liftout_v1\n"
        f"report_path: {report_path}\n"
    )
    task_environment = ExportingTaskEnvironment()

    report = run_agent_benchmark(
        config,
        agent="claudecode",
        workspace_root=tmp_path / "workspaces",
        instrument_checkout=ROOT,
        repository_paths=RepositoryPaths(TASKS, EVALUATOR),
        agent_runner_factory=NoOpAgent,
        task_environment_runner_factory=lambda: task_environment,
        environ={
            "INSTRBENCH_AGENT_MODEL": "smoke-model",
            "ANTHROPIC_BASE_URL": "https://gateway.example.test",
            "ANTHROPIC_AUTH_TOKEN": "not-used",
        },
    )

    assert task_environment.finalized is True
    assert report["candidate_complete"] is True
    assert len(report["candidate"]["files"]) == 40
    assert list(report["steps"]) == ["step_1", "step_2", "step_3", "step_4"]
    shape_metrics = [
        criterion["metrics"]
        for step in report["steps"].values()
        for criterion in step["rubric"]["criteria"].values()
        if "candidate_geometry_sha256" in criterion["metrics"]
    ]
    assert shape_metrics
    assert any(
        metrics["candidate_geometry_sha256"]
        != metrics["reference_geometry_sha256"]
        for metrics in shape_metrics
    )
    assert 0.0 < report["score"] < 100.0
    assert report["strict_pass"] is False
    assert report["source_id"] == "openfibsem"
    assert "evaluator_id" not in report
