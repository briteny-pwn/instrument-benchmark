from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from instrument_benchmark.task_environment import (
    DockerTaskEnvironmentRunner,
    TaskEnvironmentError,
    TaskEnvironmentHandle,
)


class RecordingRunner(DockerTaskEnvironmentRunner):
    def __init__(self, *, fail_remove: bool = False, running: bool = True) -> None:
        super().__init__()
        self.commands: list[tuple[str, ...]] = []
        self.fail_remove = fail_remove
        self.running = running

    def _run(self, command, label, *, allow_failure=False):
        self.commands.append(tuple(command))
        if command[1] == "inspect":
            return subprocess.CompletedProcess(
                command, 0, "true" if self.running else "false", ""
            )
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

    def _wait_ready(self, container_id: str, endpoint: Path, ready: Path) -> None:
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
    handle.evidence_root.mkdir()
    (handle.evidence_root / "environment-result.json").write_text(
        json.dumps({"run_id": "", "status": "completed", "diagnostics": []})
    )

    with pytest.raises(TaskEnvironmentError, match="remove"):
        runner.finalize(handle)


def test_socket_path_alone_does_not_mark_task_environment_ready(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner(running=False)
    runner.ready_timeout = 0.01
    endpoint = tmp_path / "task.sock"
    ready = tmp_path / "task.ready"
    endpoint.touch()

    with pytest.raises(TaskEnvironmentError, match="becoming ready"):
        runner._wait_ready("container-id", endpoint, ready)

    ready.touch()
    with pytest.raises(TaskEnvironmentError):
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
    assert f"--user={os.getuid()}:{os.getgid()}" in docker_run
    assert handle.transport_root is not None
    assert handle.environment == {
        "DEMO_SOCKET": str(handle.transport_root / "task.sock")
    }
    assert runner.readiness == (
        handle.transport_root / "task.sock",
        handle.transport_root / "task.ready",
    )
    assert len(handle.environment["DEMO_SOCKET"].encode()) <= 100
    (handle.evidence_root / "environment-result.json").write_text(
        json.dumps(
            {"run_id": "run-1", "status": "candidate_incomplete", "diagnostics": []}
        )
    )
    result = runner.finalize(handle)
    assert result.status == "candidate_incomplete"
    assert not handle.transport_root.exists()
    assert handle.candidate_root.exists()


def test_missing_terminal_result_still_cleans_container(tmp_path):
    runner = RecordingRunner()
    handle = TaskEnvironmentHandle(tmp_path, tmp_path, {}, "container-id")
    with pytest.raises(TaskEnvironmentError, match="result"):
        runner.finalize(handle)
    assert any(command[1] == "rm" for command in runner.commands)


def test_ready_requires_readable_mount_probes_and_connectable_socket(tmp_path):
    import socket

    from instrument_benchmark.task_environment_resources import TaskEnvironmentResources
    from instrument_benchmark.task_environment_status import EnvironmentStatusReader

    runner = RecordingRunner()
    resources = runner._resources = TaskEnvironmentResources.allocate(tmp_path / "run")
    runner._status = EnvironmentStatusReader(resources.evidence_root, "r")
    endpoint = resources.transport_root / "task.sock"
    ready = resources.transport_root / "task.ready"
    probes = {}
    for name, root in (
        ("candidate", resources.candidate_root),
        ("evidence", resources.evidence_root),
    ):
        nonce = ("a" if name == "candidate" else "b") * 32
        file = f".instrbench-probe-{nonce}"
        (root / file).write_text(nonce)
        probes[name] = {"file": file, "nonce": nonce}
    ready.write_text(json.dumps({"run_id": "r", "probes": probes}))
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(endpoint))
            server.listen(1)
            runner._validate_ready(endpoint, ready)
            connection, _ = server.accept()
            with connection:
                assert connection.recv(1) == b""
        assert not list(resources.candidate_root.iterdir())
        assert not list(resources.evidence_root.iterdir())
    finally:
        resources.close_transport()


def test_live_monitor_surfaces_source_failure_and_checks_unexpected_exit(tmp_path):
    from instrument_benchmark.task_environment_status import EnvironmentStatusReader

    runner = RecordingRunner(running=False)
    runner._status = EnvironmentStatusReader(tmp_path, "r")
    handle = TaskEnvironmentHandle(tmp_path, tmp_path, {}, "container-id", run_id="r")
    (tmp_path / "environment-events.jsonl").write_text(
        json.dumps(
            {
                "run_id": "r",
                "sequence": 1,
                "kind": "environment_error",
                "step": "step_1",
                "error_type": "PermissionError",
                "error": "export denied",
                "logs": [],
            }
        )
        + "\n"
    )
    with pytest.raises(TaskEnvironmentError, match="export denied") as caught:
        runner.check_health(handle)
    assert caught.value.environment_diagnostic.step == "step_1"
    (tmp_path / "environment-events.jsonl").unlink()
    runner._status = EnvironmentStatusReader(tmp_path, "r")
    with pytest.raises(TaskEnvironmentError, match="exited"):
        runner.check_health(handle)


def test_unexpected_exit_after_agent_completion_still_prevents_scoring(tmp_path):
    runner = RecordingRunner(running=False)
    (tmp_path / "environment-result.json").write_text(
        json.dumps({"run_id": "r", "status": "candidate_incomplete", "diagnostics": []})
    )
    handle = TaskEnvironmentHandle(tmp_path, tmp_path, {}, "container-id", run_id="r")
    with pytest.raises(TaskEnvironmentError, match="exited"):
        runner.finalize(handle)
    assert any(command[1] == "rm" for command in runner.commands)
