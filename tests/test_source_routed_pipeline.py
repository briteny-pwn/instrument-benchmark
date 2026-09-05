from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from instrument_benchmark.agent import AgentExecution
from instrument_benchmark.environment import RepositoryPaths
from instrument_benchmark.orchestrator import run_agent_benchmark
from instrument_benchmark.task_environment import TaskEnvironmentHandle


AGENT_ENVIRONMENT = {
    "INSTRBENCH_AGENT_MODEL": "test-model",
    "ANTHROPIC_BASE_URL": "https://gateway.example.test",
    "ANTHROPIC_AUTH_TOKEN": "secret",
}


def _fixture(tmp_path: Path) -> tuple[Path, RepositoryPaths, Path, Path]:
    instrument = tmp_path / "instrument"
    tasks = tmp_path / "tasks"
    evaluator = tmp_path / "evaluator"
    instrument.mkdir()
    leaf = tasks / "sources/demo/task"
    leaf.mkdir(parents=True)
    prompt = "Use the instrument and complete the task.\n"
    (leaf / "prompt.md").write_text(prompt)
    (leaf / "scenarios").mkdir()
    (leaf / "scenarios/input.json").write_text("{}\n")
    (leaf / "instance.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "source_id": "demo",
                "instance_id": "task",
                "task_input": {"scenario": "scenarios/input.json"},
                "visible_files": {
                    "prompt.md": hashlib.sha256(prompt.encode()).hexdigest(),
                    "scenarios/input.json": hashlib.sha256(b"{}\n").hexdigest(),
                },
            },
            sort_keys=False,
        )
    )
    (leaf.parent / "environment").mkdir(parents=True)
    (leaf.parent / "environment/Dockerfile").write_text("FROM scratch\n")
    (leaf.parent / "source.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "source_id": "demo",
                "display_name": "Demo",
                "description": "Demo task",
                "instances": ["task"],
                "candidate": {
                    "producer": "task_environment",
                    "groups": ["step_1"],
                    "files_per_group": ["result.stl", "image.png"],
                },
                "task_environment": {
                    "container": "environment/Dockerfile",
                    "socket_environment": "DEMO_SOCKET",
                },
            },
            sort_keys=False,
        )
    )
    evaluator_source = evaluator / "sources/demo"
    evaluator_source.mkdir(parents=True)
    (evaluator_source / "source.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "source_id": "demo",
                "display_name": "Demo",
                "description": "Demo evaluator",
                "evaluator": {"entrypoint": "sources.demo.evaluator:evaluate"},
            },
            sort_keys=False,
        )
    )
    report = tmp_path / "reports/run.json"
    config = tmp_path / "run.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "run_id": "run-1",
                "source_id": "demo",
                "instance_id": "task",
                "report_path": str(report),
            },
            sort_keys=False,
        )
    )
    return instrument, RepositoryPaths(tasks, evaluator), config, report


class FakeTaskRunner:
    def __init__(self) -> None:
        self.handle: TaskEnvironmentHandle | None = None
        self.finalized = False

    def start(self, **kwargs: object) -> TaskEnvironmentHandle:
        run_root = Path(kwargs["run_root"])
        candidate = run_root / "candidate"
        evidence = run_root / "task-evidence"
        candidate.mkdir()
        evidence.mkdir()
        self.handle = TaskEnvironmentHandle(
            candidate,
            evidence,
            {"DEMO_SOCKET": str(run_root / "transport/task.sock")},
        )
        return self.handle

    def finalize(self, handle: TaskEnvironmentHandle) -> None:
        assert handle is self.handle
        self.finalized = True


class FakeAgentRunner:
    def __init__(self, task: FakeTaskRunner, *, complete: bool) -> None:
        self.task = task
        self.complete = complete

    def run(self, **kwargs: object) -> AgentExecution:
        assert kwargs["environ"]["DEMO_SOCKET"].endswith("task.sock")
        assert self.task.handle is not None
        step = self.task.handle.candidate_root / "step_1"
        step.mkdir()
        (step / "result.stl").write_text("mesh")
        if self.complete:
            (step / "image.png").write_bytes(b"png")
        artifacts = Path(kwargs["artifacts_root"])
        artifacts.mkdir()
        stdout = artifacts / "stdout"
        stderr = artifacts / "stderr"
        stdout.write_text("")
        stderr.write_text("")
        return AgentExecution(
            agent="claudecode",
            model="test-model",
            isolation="trusted_host",
            status="failed",
            exit_code=1,
            duration_seconds=0.1,
            workspace=Path(kwargs["workspace"]),
            stdout_path=stdout,
            stderr_path=stderr,
            command=("claude", "-p"),
        )


class FakeEvaluatorRunner:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def evaluate(self, **kwargs: object) -> dict[str, object]:
        request = dict(kwargs["request"])
        self.requests.append(request)
        assert "evaluator_id" not in request
        assert "candidate_path" not in request
        complete = not request["missing_candidate_files"]
        return {
            "schema_version": 1,
            "source_id": request["source_id"],
            "instance_id": request["instance_id"],
            "run_id": request["run_id"],
            "status": "completed" if complete else "partial",
            "score": 100.0 if complete else 40.0,
            "candidate_complete": complete,
            "evaluator_strict_pass": complete,
        }


class FileWritingAgent:
    def run(self, **kwargs: object) -> AgentExecution:
        workspace = Path(kwargs["workspace"])
        (workspace / "solution.py").write_text("result = 42\n")
        artifacts = Path(kwargs["artifacts_root"])
        artifacts.mkdir()
        stdout = artifacts / "stdout"
        stderr = artifacts / "stderr"
        stdout.write_text("")
        stderr.write_text("")
        return AgentExecution(
            agent="claudecode",
            model="test-model",
            isolation="trusted_host",
            status="completed",
            exit_code=0,
            duration_seconds=0.1,
            workspace=workspace,
            stdout_path=stdout,
            stderr_path=stderr,
            command=("claude", "-p"),
        )


@pytest.mark.parametrize("complete", [True, False])
def test_task_environment_files_are_evaluated_even_when_agent_fails(
    tmp_path: Path, complete: bool
) -> None:
    instrument, repositories, config, report_path = _fixture(tmp_path)
    task = FakeTaskRunner()
    evaluator = FakeEvaluatorRunner()

    report = run_agent_benchmark(
        config,
        agent="claudecode",
        workspace_root=tmp_path / "workspaces",
        instrument_checkout=instrument,
        repository_paths=repositories,
        agent_runner_factory=lambda: FakeAgentRunner(task, complete=complete),
        task_environment_runner_factory=lambda: task,
        evaluator_runner_factory=lambda: evaluator,
        environ=AGENT_ENVIRONMENT,
    )

    assert task.finalized is True
    assert len(evaluator.requests) == 1
    assert report["agent_execution"]["status"] == "failed"
    assert report["evaluated"] is True
    assert report["candidate_complete"] is complete
    assert report["strict_pass"] is complete
    assert "solution.py" not in json.dumps(report)
    assert json.loads(report_path.read_text()) == report


def test_agent_producer_uses_workspace_as_candidate_handoff(tmp_path: Path) -> None:
    instrument, repositories, config, _ = _fixture(tmp_path)
    source_path = repositories.instances_repo_path / "sources/demo/source.yaml"
    source = yaml.safe_load(source_path.read_text())
    source["candidate"] = {"producer": "agent", "files": ["solution.py"]}
    source.pop("task_environment")
    source_path.write_text(yaml.safe_dump(source, sort_keys=False))
    evaluator = FakeEvaluatorRunner()

    report = run_agent_benchmark(
        config,
        agent="claudecode",
        workspace_root=tmp_path / "workspaces",
        instrument_checkout=instrument,
        repository_paths=repositories,
        agent_runner_factory=FileWritingAgent,
        task_environment_runner_factory=lambda: pytest.fail(
            "agent candidates must not start a task environment"
        ),
        evaluator_runner_factory=lambda: evaluator,
        environ=AGENT_ENVIRONMENT,
    )

    assert report["candidate"]["producer"] == "agent"
    assert report["candidate"]["files"] == ["solution.py"]
    assert report["candidate_complete"] is True
    assert evaluator.requests[0]["candidate_files"] == ["solution.py"]


def test_repeated_run_id_uses_a_fresh_candidate_handoff(tmp_path: Path) -> None:
    instrument, repositories, config, _ = _fixture(tmp_path)
    candidate_roots: list[Path] = []

    for _ in range(2):
        task = FakeTaskRunner()
        evaluator = FakeEvaluatorRunner()
        report = run_agent_benchmark(
            config,
            agent="claudecode",
            workspace_root=tmp_path / "workspaces",
            instrument_checkout=instrument,
            repository_paths=repositories,
            agent_runner_factory=lambda task=task: FakeAgentRunner(
                task, complete=True
            ),
            task_environment_runner_factory=lambda task=task: task,
            evaluator_runner_factory=lambda evaluator=evaluator: evaluator,
            environ=AGENT_ENVIRONMENT,
        )
        candidate_roots.append(Path(report["candidate"]["root"]))

    assert candidate_roots[0] != candidate_roots[1]
    assert all(path.is_dir() for path in candidate_roots)


def test_process_environment_drives_pipeline_without_injected_environ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instrument, repositories, config, _ = _fixture(tmp_path)
    for name, value in AGENT_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    task = FakeTaskRunner()
    evaluator = FakeEvaluatorRunner()

    report = run_agent_benchmark(
        config,
        agent="claudecode",
        workspace_root=tmp_path / "workspaces",
        instrument_checkout=instrument,
        repository_paths=repositories,
        agent_runner_factory=lambda: FakeAgentRunner(task, complete=True),
        task_environment_runner_factory=lambda: task,
        evaluator_runner_factory=lambda: evaluator,
    )

    assert report["candidate_complete"] is True
    assert evaluator.requests[0]["source_id"] == "demo"
