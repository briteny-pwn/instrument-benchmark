from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from instrument_benchmark.agent import AgentExecution
from instrument_benchmark.environment import RepositoryPaths
from instrument_benchmark.orchestrator import run_agent_benchmark


AGENT_ENVIRONMENT = {
    "INSTRBENCH_AGENT_MODEL": "test-model",
    "ANTHROPIC_BASE_URL": "https://gateway.example.test",
    "ANTHROPIC_AUTH_TOKEN": "secret",
}


def _write_task(
    repository: Path,
    *,
    filename: str = "answer.json",
    starter_candidate: bool = False,
) -> None:
    leaf = repository / "sources" / "demo" / "task"
    leaf.mkdir(parents=True)
    (leaf.parent / "source.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "source_id": "demo",
                "display_name": "Demo",
                "description": "Demo task",
                "instances": ["task"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    files = {
        "prompt.md": f"Write `{filename}`.\n",
        "docs/api.md": "public api\n",
    }
    if starter_candidate:
        files[f"starter/{filename}"] = "{}\n"
    visible: dict[str, str] = {}
    for relative, contents in files.items():
        path = leaf / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        visible[relative] = hashlib.sha256(contents.encode()).hexdigest()
    (leaf / "instance.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "instance_id": "task",
                "source_id": "demo",
                "visible_files": visible,
                "submission": {"filename": filename},
                "evaluator": {"id": "evaluator", "protocol_version": 2},
                "container": {"protocol_version": 1},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_evaluator(repository: Path) -> None:
    leaf = repository / "sources" / "demo" / "evaluator"
    leaf.mkdir(parents=True)
    (leaf.parent / "source.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "source_id": "demo",
                "display_name": "Demo",
                "description": "Demo evaluator",
                "evaluators": ["evaluator"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (leaf / "evaluator.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "source_id": "demo",
                "evaluator_id": "evaluator",
                "protocol_version": 2,
                "container_protocol_version": 1,
                "candidate_execution": "docker",
                "image_mode": "locked",
                "supported_instances": ["task"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _fixture(tmp_path: Path, *, starter_candidate: bool = False):
    instrument = tmp_path / "instrument"
    tasks = tmp_path / "tasks"
    evaluator = tmp_path / "evaluator"
    instrument.mkdir()
    evaluator.mkdir()
    _write_task(tasks, starter_candidate=starter_candidate)
    _write_evaluator(evaluator)
    config = tmp_path / "run.yaml"
    report = tmp_path / "reports" / "run.json"
    config.write_text(
        yaml.safe_dump(
            {
                "run_id": "agent-run",
                "source_id": "demo",
                "instance_id": "task",
                "evaluator_id": "evaluator",
                "report_path": str(report),
                "timeout_seconds": 30,
                "max_output_bytes": 1024,
                "repeated_worlds": 1,
                "repeated_base_seed": 1,
                "container_protocol_version": 1,
                "image_mode": "locked",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return (
        instrument,
        RepositoryPaths(tasks, evaluator),
        config,
        report,
    )


class FakeAgentRunner:
    def __init__(self, *, status: str, create_candidate: bool) -> None:
        self.status = status
        self.create_candidate = create_candidate
        self.calls: list[dict[str, object]] = []

    def run(self, **kwargs: object) -> AgentExecution:
        self.calls.append(kwargs)
        workspace = Path(kwargs["workspace"])
        artifacts = Path(kwargs["artifacts_root"])
        artifacts.mkdir(parents=True, exist_ok=True)
        if self.create_candidate:
            (workspace / "answer.json").write_text('{"answer": 42}\n')
        stdout = artifacts / "agent-output.jsonl"
        stderr = artifacts / "agent-stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return AgentExecution(
            agent="claudecode",
            model="test-model",
            isolation="trusted_host",
            status=self.status,
            exit_code=0 if self.status == "completed" else 1,
            duration_seconds=1.5,
            workspace=workspace,
            stdout_path=stdout,
            stderr_path=stderr,
            command=("claude", "-p"),
        )


@pytest.mark.parametrize("agent_status", ["completed", "failed", "timeout"])
def test_agent_candidate_is_evaluated_for_every_agent_exit_status(
    tmp_path: Path, agent_status: str
) -> None:
    instrument, repositories, config, report_path = _fixture(tmp_path)
    agent_runner = FakeAgentRunner(status=agent_status, create_candidate=True)
    evaluator_calls: list[dict[str, object]] = []

    def evaluator_runner(config_path: Path, **kwargs: object) -> dict[str, object]:
        evaluator_calls.append({"config_path": config_path, **kwargs})
        candidate = Path(kwargs["candidate_path"])
        assert candidate.name == "answer.json"
        assert json.loads(candidate.read_text()) == {"answer": 42}
        return {"status": "completed", "score": 80.0, "strict_pass": False}

    result = run_agent_benchmark(
        config,
        agent="claudecode",
        workspace_root=tmp_path / "workspaces",
        instrument_checkout=instrument,
        repository_paths=repositories,
        agent_runner_factory=lambda: agent_runner,
        benchmark_runner=evaluator_runner,
        environ=AGENT_ENVIRONMENT,
    )

    assert len(evaluator_calls) == 1
    assert result["score"] == 80.0
    assert result["agent_execution"]["status"] == agent_status
    assert result["agent_execution"]["candidate_path"].endswith("answer.json")
    assert len(result["agent_execution"]["candidate_sha256"]) == 64
    assert result["candidate_available"] is True
    assert result["evaluated"] is True
    assert json.loads(report_path.read_text()) == result


def test_missing_candidate_is_zero_score_without_evaluator(tmp_path: Path) -> None:
    instrument, repositories, config, report_path = _fixture(tmp_path)
    agent_runner = FakeAgentRunner(status="completed", create_candidate=False)
    evaluator_calls: list[object] = []

    result = run_agent_benchmark(
        config,
        agent="claudecode",
        workspace_root=tmp_path / "workspaces",
        instrument_checkout=instrument,
        repository_paths=repositories,
        agent_runner_factory=lambda: agent_runner,
        benchmark_runner=lambda *args, **kwargs: evaluator_calls.append((args, kwargs)),
        environ=AGENT_ENVIRONMENT,
    )

    assert evaluator_calls == []
    assert result["status"] == "missing_submission"
    assert result["score"] == 0.0
    assert result["strict_pass"] is False
    assert result["candidate_available"] is False
    assert result["evaluated"] is False
    assert result["agent_execution"]["candidate_path"] is None
    assert json.loads(report_path.read_text()) == result


def test_failed_agent_starter_candidate_is_still_evaluated(tmp_path: Path) -> None:
    instrument, repositories, config, _ = _fixture(
        tmp_path, starter_candidate=True
    )
    agent_runner = FakeAgentRunner(status="failed", create_candidate=False)
    candidates: list[Path] = []

    def evaluator_runner(_: Path, **kwargs: object) -> dict[str, object]:
        candidates.append(Path(kwargs["candidate_path"]))
        return {"status": "completed", "score": 1.0, "strict_pass": False}

    result = run_agent_benchmark(
        config,
        agent="claudecode",
        workspace_root=tmp_path / "workspaces",
        instrument_checkout=instrument,
        repository_paths=repositories,
        agent_runner_factory=lambda: agent_runner,
        benchmark_runner=evaluator_runner,
        environ=AGENT_ENVIRONMENT,
    )

    assert len(candidates) == 1
    assert result["agent_execution"]["candidate_changed"] is False


def test_directory_submission_is_rejected_without_evaluator(tmp_path: Path) -> None:
    instrument, repositories, config, _ = _fixture(tmp_path)

    class DirectoryAgentRunner(FakeAgentRunner):
        def run(self, **kwargs: object) -> AgentExecution:
            execution = super().run(**kwargs)
            Path(kwargs["workspace"], "answer.json").mkdir()
            return execution

    agent_runner = DirectoryAgentRunner(status="completed", create_candidate=False)
    evaluator_calls: list[object] = []

    result = run_agent_benchmark(
        config,
        agent="claudecode",
        workspace_root=tmp_path / "workspaces",
        instrument_checkout=instrument,
        repository_paths=repositories,
        agent_runner_factory=lambda: agent_runner,
        benchmark_runner=lambda *args, **kwargs: evaluator_calls.append((args, kwargs)),
        environ=AGENT_ENVIRONMENT,
    )

    assert evaluator_calls == []
    assert result["status"] == "submission_error"
    assert result["score"] == 0.0
    assert result["candidate_available"] is False
    assert "regular file" in result["error"]


def test_rejects_unknown_agent_before_starting_runner(tmp_path: Path) -> None:
    instrument, repositories, config, _ = _fixture(tmp_path)
    runner_created = False

    def factory() -> FakeAgentRunner:
        nonlocal runner_created
        runner_created = True
        return FakeAgentRunner(status="completed", create_candidate=True)

    with pytest.raises(ValueError, match="unsupported agent"):
        run_agent_benchmark(
            config,
            agent="unknown",
            workspace_root=tmp_path / "workspaces",
            instrument_checkout=instrument,
            repository_paths=repositories,
            agent_runner_factory=factory,
            environ=AGENT_ENVIRONMENT,
        )

    assert runner_created is False


def test_rejects_task_evaluator_mismatch_before_starting_agent(
    tmp_path: Path,
) -> None:
    instrument, repositories, config, _ = _fixture(tmp_path)
    manifest_path = (
        repositories.evaluator_repo_path
        / "sources"
        / "demo"
        / "evaluator"
        / "evaluator.yaml"
    )
    manifest = yaml.safe_load(manifest_path.read_text())
    manifest["supported_instances"] = ["other_task"]
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    runner_created = False

    def factory() -> FakeAgentRunner:
        nonlocal runner_created
        runner_created = True
        return FakeAgentRunner(status="completed", create_candidate=True)

    with pytest.raises(ValueError, match="not supported by evaluator"):
        run_agent_benchmark(
            config,
            agent="claudecode",
            workspace_root=tmp_path / "workspaces",
            instrument_checkout=instrument,
            repository_paths=repositories,
            agent_runner_factory=factory,
            environ=AGENT_ENVIRONMENT,
        )

    assert runner_created is False
