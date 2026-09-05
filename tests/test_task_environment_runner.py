from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from instrument_benchmark.task_environment import (
    DockerTaskEnvironmentRunner,
    TaskEnvironmentError,
    TaskEnvironmentHandle,
)


class RecordingRunner(DockerTaskEnvironmentRunner):
    def __init__(self, *, fail_remove: bool = False) -> None:
        super().__init__()
        self.commands: list[tuple[str, ...]] = []
        self.fail_remove = fail_remove

    def _run(self, command, label, *, allow_failure=False):
        self.commands.append(tuple(command))
        if len(command) > 1 and command[1] == "run":
            return subprocess.CompletedProcess(command, 0, "container-id\n", "")
        if len(command) > 1 and command[1] == "logs":
            return subprocess.CompletedProcess(command, 0, "container log\n", "")
        if len(command) > 1 and command[1] == "rm" and self.fail_remove:
            if allow_failure:
                return subprocess.CompletedProcess(command, 1, "", "remove failed")
            raise TaskEnvironmentError("cannot remove task environment")
        return subprocess.CompletedProcess(command, 0, "", "")


class ReadyRecordingRunner(RecordingRunner):
    def __init__(self) -> None:
        super().__init__()
        self.readiness: tuple[Path, Path] | None = None

    def _wait_ready(
        self, container_id: str, endpoint: Path, ready: Path
    ) -> None:
        assert container_id == "container-id"
        self.readiness = (endpoint, ready)


def test_log_write_failure_still_removes_task_container(tmp_path: Path) -> None:
    runner = RecordingRunner()

    runner._collect_and_remove("container-id", tmp_path / "missing/log.txt")

    assert any(command[1:3] == ("rm", "--force") for command in runner.commands)


def test_finalize_reports_container_removal_failure(tmp_path: Path) -> None:
    runner = RecordingRunner(fail_remove=True)
    handle = TaskEnvironmentHandle(
        tmp_path / "candidate",
        tmp_path / "evidence",
        {},
        container_id="container-id",
        log_path=tmp_path / "task.log",
    )

    with pytest.raises(TaskEnvironmentError, match="remove"):
        runner.finalize(handle)


def test_socket_path_alone_does_not_mark_task_environment_ready(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    runner.ready_timeout = 0.01
    endpoint = tmp_path / "task.sock"
    ready = tmp_path / "task.ready"
    endpoint.touch()

    with pytest.raises(TaskEnvironmentError, match="becoming ready"):
        runner._wait_ready("container-id", endpoint, ready)

    ready.touch()
    runner._wait_ready("container-id", endpoint, ready)


def test_task_environment_mounts_generic_instance_contract(
    tmp_path: Path,
) -> None:
    tasks = tmp_path / "tasks"
    dockerfile = tasks / "sources/demo/environment/Dockerfile"
    dockerfile.parent.mkdir(parents=True)
    dockerfile.write_text("FROM scratch\n")
    instance = tasks / "sources/demo/example"
    instance.mkdir()
    (instance / "instance.yaml").write_text("source_id: demo\n")
    runner = ReadyRecordingRunner()

    handle = runner.start(
        tasks_checkout=tasks,
        source_manifest={
            "source_id": "demo",
            "task_environment": {
                "container": "environment/Dockerfile",
                "socket_environment": "DEMO_SOCKET",
            },
        },
        instance_root=instance,
        instance_manifest={"source_id": "demo"},
        run_root=tmp_path / "run",
        run_id="run-1",
    )

    docker_run = next(command for command in runner.commands if command[1] == "run")
    rendered = "\n".join(docker_run)
    assert f"--volume={instance.resolve()}:/task/instance:ro" in docker_run
    assert "--env=INSTRBENCH_TASK_INSTANCE_ROOT=/task/instance" in docker_run
    assert "--env=INSTRBENCH_TASK_SOCKET=/run/instrbench/task.sock" in docker_run
    assert "FIBSEM" not in rendered
    assert "scenario.json" not in rendered
    assert handle.environment == {
        "DEMO_SOCKET": str(handle.candidate_root.parent / "transport/task.sock")
    }
    assert runner.readiness == (
        handle.candidate_root.parent / "transport/task.sock",
        handle.candidate_root.parent / "transport/task.ready",
    )
