from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .contracts import ContractError


class TaskEnvironmentError(RuntimeError):
    """The source-owned task environment could not be started or finalized."""


@dataclass(frozen=True)
class TaskEnvironmentHandle:
    candidate_root: Path
    evidence_root: Path
    environment: dict[str, str]
    container_id: str | None = None
    log_path: Path | None = None


class TaskEnvironmentRunner(Protocol):
    def start(
        self,
        *,
        tasks_checkout: Path,
        source_manifest: Mapping[str, Any],
        instance_root: Path,
        instance_manifest: Mapping[str, Any],
        run_root: Path,
        run_id: str,
    ) -> TaskEnvironmentHandle: ...

    def finalize(self, handle: TaskEnvironmentHandle) -> None: ...


class DockerTaskEnvironmentRunner:
    def __init__(
        self,
        *,
        docker_executable: str = "docker",
        ready_timeout: float = 30.0,
    ) -> None:
        self.docker_executable = docker_executable
        self.ready_timeout = ready_timeout

    def start(
        self,
        *,
        tasks_checkout: Path,
        source_manifest: Mapping[str, Any],
        instance_root: Path,
        instance_manifest: Mapping[str, Any],
        run_root: Path,
        run_id: str,
    ) -> TaskEnvironmentHandle:
        task_environment = source_manifest.get("task_environment")
        if not isinstance(task_environment, Mapping):
            raise ContractError("source task_environment is missing")
        container = task_environment.get("container")
        socket_environment = task_environment.get("socket_environment")
        if not isinstance(container, str) or not isinstance(socket_environment, str):
            raise ContractError("source task_environment contract is invalid")
        dockerfile = (
            source_manifest_path_root(tasks_checkout, source_manifest) / container
        ).resolve()
        checkout = tasks_checkout.resolve()
        if not dockerfile.is_relative_to(checkout) or not dockerfile.is_file():
            raise ContractError("task environment Dockerfile is invalid")
        source_id = str(source_manifest["source_id"])
        image = f"instrbench-task-{source_id}:local"
        self._run(
            [
                self.docker_executable,
                "build",
                "--tag",
                image,
                "--file",
                str(dockerfile),
                str(checkout),
            ],
            "build task environment",
        )

        candidate = run_root / "candidate"
        evidence = run_root / "task-evidence"
        transport = run_root / "transport"
        for path in (candidate, evidence, transport):
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(0o777)
        instance = instance_root.resolve()
        if not instance.is_relative_to(checkout) or not instance.is_dir():
            raise ContractError("task instance root is invalid")
        endpoint_in_container = Path("/run/instrbench/task.sock")
        ready_in_container = Path("/run/instrbench/task.ready")
        endpoint_on_host = transport / endpoint_in_container.name
        ready_on_host = transport / ready_in_container.name
        name = _container_name(run_id)
        command = [
            self.docker_executable,
            "run",
            "--detach",
            f"--name={name}",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=128m",
            f"--volume={candidate}:/candidate:rw",
            f"--volume={evidence}:/evidence:rw",
            f"--volume={transport}:/run/instrbench:rw",
            f"--volume={instance}:/task/instance:ro",
            "--env=INSTRBENCH_TASK_INSTANCE_ROOT=/task/instance",
            f"--env=INSTRBENCH_TASK_SOCKET={endpoint_in_container}",
            f"--env=INSTRBENCH_TASK_READY={ready_in_container}",
            "--env=INSTRBENCH_CANDIDATE_ROOT=/candidate",
            "--env=INSTRBENCH_TASK_EVIDENCE_ROOT=/evidence",
            f"--env=INSTRBENCH_RUN_ID={run_id}",
            f"--env=INSTRBENCH_AGENT_UID={os.getuid()}",
            image,
        ]
        completed = self._run(command, "start task environment")
        container_id = completed.stdout.strip()
        if not container_id:
            raise TaskEnvironmentError(
                "Docker returned no task environment container ID"
            )
        log_path = run_root / "task-environment.log"
        try:
            self._wait_ready(container_id, endpoint_on_host, ready_on_host)
        except BaseException:
            self._collect_and_remove(container_id, log_path)
            raise
        return TaskEnvironmentHandle(
            candidate.resolve(),
            evidence.resolve(),
            {socket_environment: str(endpoint_on_host.resolve())},
            container_id,
            log_path,
        )

    def finalize(self, handle: TaskEnvironmentHandle) -> None:
        if handle.container_id is None:
            return
        self._run(
            [self.docker_executable, "stop", "--time=5", handle.container_id],
            "stop task environment",
            allow_failure=True,
        )
        self._collect_and_remove(handle.container_id, handle.log_path)

    def _wait_ready(
        self, container_id: str, endpoint: Path, ready: Path
    ) -> None:
        deadline = time.monotonic() + self.ready_timeout
        while time.monotonic() < deadline:
            if endpoint.exists() and ready.is_file():
                return
            state = self._run(
                [
                    self.docker_executable,
                    "inspect",
                    "--format={{.State.Running}}",
                    container_id,
                ],
                "inspect task environment",
                allow_failure=True,
            )
            if state.returncode != 0 or state.stdout.strip() != "true":
                raise TaskEnvironmentError(
                    "task environment exited before becoming ready"
                )
            time.sleep(0.05)
        raise TaskEnvironmentError("task environment did not become ready")

    def _collect_and_remove(self, container_id: str, log_path: Path | None) -> None:
        logs = self._run(
            [self.docker_executable, "logs", container_id],
            "collect task environment logs",
            allow_failure=True,
        )
        try:
            if log_path is not None:
                log_path.write_text(logs.stdout + logs.stderr, encoding="utf-8")
        except OSError:
            # Logs are diagnostic only; cleanup and candidate evaluation must proceed.
            pass
        self._run(
            [self.docker_executable, "rm", "--force", container_id],
            "remove task environment",
        )

    @staticmethod
    def _run(
        command: list[str], label: str, *, allow_failure: bool = False
    ) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except OSError as exc:
            raise TaskEnvironmentError(f"cannot {label}: {exc}") from exc
        if completed.returncode != 0 and not allow_failure:
            details = completed.stderr.strip() or completed.stdout.strip()
            raise TaskEnvironmentError(
                f"cannot {label}: {details}"
            )
        return completed


def source_manifest_path_root(
    tasks_checkout: Path, source_manifest: Mapping[str, Any]
) -> Path:
    return tasks_checkout.resolve() / "sources" / str(source_manifest["source_id"])


def _container_name(run_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "-", run_id)[:48]
    return f"instrbench-task-{safe}-{os.getpid()}"
