from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest
from test_source_routed_pipeline import AGENT_ENVIRONMENT, FakeTaskRunner, _fixture

from instrument_benchmark.diagnostics import Redactor
from instrument_benchmark.orchestrator import run_agent_benchmark
from instrument_benchmark.progress import ProgressReporter
from instrument_benchmark.suite import load_suite_config, run_suite
from instrument_benchmark.task_environment import (
    DockerTaskEnvironmentRunner,
    TaskEnvironmentHandle,
)


@pytest.mark.parametrize(
    "rendered",
    [
        '{"Authorization": "Bearer unknown-json-token", "ok": true}',
        "{'Authorization': 'Basic unknown-dict-token', 'ok': True}",
        "Authorization: Bearer unknown-header-token",
        r"{\"Authorization\":\"Bearer unknown-escaped-token\",\"ok\":true}",
    ],
)
def test_redactor_hides_unknown_authorization_credentials(rendered: str) -> None:
    sanitized = Redactor()(rendered)

    assert "unknown" not in sanitized
    assert "[REDACTED]" in sanitized
    if rendered.startswith('{"'):
        json.loads(sanitized)


def test_redactor_preserves_normal_json_and_known_secret_redaction() -> None:
    rendered = '\x1b[31m{"message": "normal", "token": "known-secret"}\x1b[0m'

    sanitized = Redactor(["known-secret"])(rendered)

    assert json.loads(sanitized) == {"message": "normal", "token": "[REDACTED]"}


def _docker_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    tasks = tmp_path / "tasks"
    dockerfile = tasks / "sources/demo/environment/Dockerfile"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text("FROM scratch\n")
    instance = tasks / "sources/demo/example"
    instance.mkdir()
    return (
        tasks,
        instance,
        {
            "source_id": "demo",
            "task_environment": {
                "container": "environment/Dockerfile",
                "socket_environment": "DEMO_SOCKET",
            },
        },
    )


def test_docker_launch_error_removes_unique_attempt_name(tmp_path: Path) -> None:
    tasks, instance, source = _docker_fixture(tmp_path)

    class Runner(DockerTaskEnvironmentRunner):
        def __init__(self) -> None:
            super().__init__()
            self.commands: list[tuple[str, ...]] = []

        def _run(self, command, label, *, allow_failure=False):
            self.commands.append(tuple(command))
            if command[1] == "run":
                raise RuntimeError("callback failed after create")
            return subprocess.CompletedProcess(command, 0, "", "")

    runner = Runner()
    with pytest.raises(RuntimeError, match="callback failed"):
        runner.start(
            tasks_checkout=tasks,
            source_manifest=source,
            instance_root=instance,
            instance_manifest={"source_id": "demo"},
            run_root=tmp_path / "run",
            run_id="same-run",
        )

    run_command = next(command for command in runner.commands if command[1] == "run")
    name = next(
        item.removeprefix("--name=")
        for item in run_command
        if item.startswith("--name=")
    )
    assert ("docker", "rm", "--force", name) in runner.commands


def test_cleanup_keyboard_interrupt_replaces_ordinary_agent_failure_and_stops_suite(
    tmp_path: Path,
) -> None:
    instrument, repositories, config, _ = _fixture(tmp_path)
    second = tmp_path / "run2.yaml"
    second.write_text(
        config.read_text().replace("run-1", "run-2").replace("run.json", "run2.json")
    )
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        "suite_id: example\nagent: claudecode\n"
        "runs: [run.yaml, run2.yaml]\nresult_path: suite.json\n"
    )
    seen: list[Path] = []

    class Agent:
        def run(self, **kwargs):
            raise RuntimeError("agent failed")

    class Task(FakeTaskRunner):
        def finalize(self, handle):
            raise KeyboardInterrupt()

    def benchmark(path, **kwargs):
        seen.append(path)
        return run_agent_benchmark(
            path,
            **kwargs,
            environ=AGENT_ENVIRONMENT,
            agent_runner_factory=Agent,
            task_environment_runner_factory=Task,
        )

    with ProgressReporter(stream=io.StringIO()):
        with pytest.raises(KeyboardInterrupt):
            run_suite(
                load_suite_config(suite_path, repositories),
                instrument_checkout=instrument,
                repository_paths=repositories,
                benchmark_runner=benchmark,
            )

    assert seen == [config.resolve()]
    report = json.loads((tmp_path / "suite.json").read_text())
    assert report["interrupted"] is True
    assert report["runs"][0]["status"] == "interrupted"
    assert any(
        "agent failed" in item["error"] for item in report["runs"][0]["diagnostics"]
    )


def test_docker_cleanup_interrupt_propagates_after_readiness_failure(
    tmp_path: Path,
) -> None:
    tasks, instance, source = _docker_fixture(tmp_path)

    class Runner(DockerTaskEnvironmentRunner):
        def _run(self, command, label, *, allow_failure=False):
            if command[1] == "run":
                return subprocess.CompletedProcess(command, 0, "container-id\n", "")
            if command[1] == "rm":
                raise KeyboardInterrupt()
            return subprocess.CompletedProcess(command, 0, "", "")

        def _wait_ready(self, container_id, endpoint, ready):
            raise RuntimeError("readiness failed")

    with pytest.raises(KeyboardInterrupt):
        Runner().start(
            tasks_checkout=tasks,
            source_manifest=source,
            instance_root=instance,
            instance_manifest={"source_id": "demo"},
            run_root=tmp_path / "run",
            run_id="run-1",
        )


def test_finalize_preserves_primary_keyboard_interrupt_over_remove_error(
    tmp_path: Path,
) -> None:
    class Runner(DockerTaskEnvironmentRunner):
        def _run(self, command, label, *, allow_failure=False):
            if command[1] == "stop":
                raise KeyboardInterrupt()
            if command[1] == "rm":
                raise RuntimeError("remove failed")
            return subprocess.CompletedProcess(command, 0, "", "")

    handle = TaskEnvironmentHandle(tmp_path, tmp_path, {}, "container-id")
    with pytest.raises(KeyboardInterrupt):
        Runner().finalize(handle)


def test_log_collection_interrupt_is_not_masked_by_remove_error() -> None:
    class Runner(DockerTaskEnvironmentRunner):
        def _run(self, command, label, *, allow_failure=False):
            if command[1] == "logs":
                raise KeyboardInterrupt()
            raise RuntimeError("remove failed")

    with pytest.raises(KeyboardInterrupt):
        Runner()._collect_and_remove("container-id", None)
