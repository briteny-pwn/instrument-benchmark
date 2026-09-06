from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .contracts import ContractError
from .diagnostics import Redactor
from .progress import current_progress, operation
from .streaming_process import stream_process
from .task_environment_resources import TaskEnvironmentResources
from .task_environment_status import (
    EnvironmentDiagnostic,
    EnvironmentStatusReader,
    TaskEnvironmentResult,
    TaskEnvironmentStatusError,
    _regular_file,
)


class TaskEnvironmentError(RuntimeError):
    """The source-owned task environment could not be started or finalized."""

    def __init__(
        self, message: str, *, diagnostic: EnvironmentDiagnostic | None = None
    ):
        super().__init__(message)
        self.environment_diagnostic = diagnostic


@dataclass(frozen=True)
class TaskEnvironmentHandle:
    candidate_root: Path
    evidence_root: Path
    environment: dict[str, str]
    container_id: str | None = None
    log_path: Path | None = None
    run_id: str = ""
    transport_root: Path | None = None


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

    def finalize(self, handle: TaskEnvironmentHandle) -> TaskEnvironmentResult: ...

    def check_health(self, handle: TaskEnvironmentHandle) -> None: ...


class DockerTaskEnvironmentRunner:
    def __init__(
        self,
        *,
        docker_executable: str = "docker",
        ready_timeout: float = 30.0,
    ) -> None:
        self.docker_executable = docker_executable
        self.ready_timeout = ready_timeout
        self._log_root: Path | None = None
        self._command_index = 0
        self._last_logs: tuple[Path, Path] | None = None
        self._resources: TaskEnvironmentResources | None = None
        self._status: EnvironmentStatusReader | None = None
        self._next_health_check = 0.0
        self.last_result: TaskEnvironmentResult | None = None

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
        self._log_root = run_root.resolve()
        operation("校验任务环境定义")
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
        instance = instance_root.resolve()
        if not instance.is_relative_to(checkout) or not instance.is_dir():
            raise ContractError("task instance root is invalid")
        if os.getuid() == 0 or os.getgid() == 0:
            raise TaskEnvironmentError(
                "task environment requires a non-root host UID/GID"
            )
        source_id = str(source_manifest["source_id"])
        image = f"instrbench-task-{source_id}:local"
        self._run(
            [
                self.docker_executable,
                "build",
                "--progress=plain",
                "--tag",
                image,
                "--file",
                str(dockerfile),
                str(checkout),
            ],
            "build task environment",
        )

        self._resources = TaskEnvironmentResources.allocate(run_root.resolve())
        candidate = self._resources.candidate_root
        evidence = self._resources.evidence_root
        transport = self._resources.transport_root
        self._status = EnvironmentStatusReader(evidence, run_id)
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
            f"--user={os.getuid()}:{os.getgid()}",
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
        log_path = run_root / "task-environment.log"
        container_id: str | None = None
        try:
            completed = self._run(command, "start task environment")
            container_id = completed.stdout.strip()
            if not container_id:
                raise TaskEnvironmentError(
                    "Docker returned no task environment container ID"
                )
            log_path.touch()
            operation(
                "校验挂载读写与 socket 就绪",
                logs=[log_path],
                timeout_seconds=self.ready_timeout,
            )
            self._wait_ready(container_id, endpoint_on_host, ready_on_host)
        except BaseException as exc:
            progress = current_progress()
            if progress:
                progress.record_error(exc)
            try:
                self._collect_and_remove(container_id or name, log_path)
            except BaseException as cleanup_error:
                exc.add_note(f"task environment cleanup: {cleanup_error}")
                if progress:
                    progress.record_error(cleanup_error)
                if isinstance(cleanup_error, KeyboardInterrupt):
                    raise
            finally:
                self._close_transport(exc)
            if self._status is not None:
                try:
                    self.last_result = self._status.read_result()
                except (TaskEnvironmentStatusError, OSError) as status_error:
                    exc.add_note(f"task environment terminal evidence: {status_error}")
            raise
        return TaskEnvironmentHandle(
            candidate.resolve(),
            evidence.resolve(),
            {socket_environment: str(endpoint_on_host.resolve())},
            container_id,
            log_path,
            run_id,
            transport,
        )

    def finalize(self, handle: TaskEnvironmentHandle) -> TaskEnvironmentResult:
        primary: BaseException | None = None
        try:
            was_running = True
            if handle.container_id is not None:
                state = self._run(
                    [
                        self.docker_executable,
                        "inspect",
                        "--format={{.State.Running}}",
                        handle.container_id,
                    ],
                    "inspect task environment",
                    allow_failure=True,
                )
                was_running = state.returncode == 0 and state.stdout.strip() == "true"
                self._run(
                    [self.docker_executable, "stop", "--time=5", handle.container_id],
                    "stop task environment",
                )
            try:
                reader = self._status or EnvironmentStatusReader(
                    handle.evidence_root, handle.run_id
                )
                self.last_result = reader.read_result()
            except (TaskEnvironmentStatusError, OSError) as exc:
                raise TaskEnvironmentError(
                    f"invalid task environment result: {exc}"
                ) from exc
            if not was_running and self.last_result.status != "infrastructure_failure":
                raise TaskEnvironmentError(
                    "task environment exited before Instrument requested shutdown"
                )
            return self.last_result
        except BaseException as exc:
            primary = exc
            if current_progress():
                current_progress().record_error(exc)
            raise
        finally:
            try:
                if handle.container_id is not None:
                    self._collect_and_remove(handle.container_id, handle.log_path)
            except BaseException as exc:
                if current_progress():
                    current_progress().record_error(exc)
                if primary is None or isinstance(exc, KeyboardInterrupt):
                    primary = exc
                    raise
                primary.add_note(f"task environment cleanup: {exc}")
            finally:
                self._close_transport(primary)

    def _close_transport(self, primary: BaseException | None) -> None:
        if self._resources is not None:
            try:
                self._resources.close_transport()
            except Exception as exc:
                if primary is None:
                    raise TaskEnvironmentError(
                        f"cannot remove task transport: {exc}"
                    ) from exc
                primary.add_note(f"task transport cleanup: {exc}")

    def _poll_status(self) -> None:
        if self._status is None:
            raise TaskEnvironmentError("task environment status reader is missing")
        try:
            self._status.poll()
        except (TaskEnvironmentStatusError, OSError) as exc:
            raise TaskEnvironmentError(
                f"cannot read task environment status: {exc}"
            ) from exc
        if self._status.fatal is not None:
            diagnostic = self._status.fatal
            raise TaskEnvironmentError(
                f"{diagnostic.error_type}: {diagnostic.error}", diagnostic=diagnostic
            )

    def check_health(self, handle: TaskEnvironmentHandle) -> None:
        self._poll_status()
        now = time.monotonic()
        if handle.container_id is None or now < self._next_health_check:
            return
        self._next_health_check = now + 1.0
        state = self._run(
            [
                self.docker_executable,
                "inspect",
                "--format={{.State.Running}}",
                handle.container_id,
            ],
            "inspect task environment",
            allow_failure=True,
        )
        if state.returncode != 0 or state.stdout.strip() != "true":
            # Drain the error which may have been published immediately before exit.
            self._poll_status()
            raise TaskEnvironmentError(
                "task environment exited while Agent was running"
            )

    def _wait_ready(self, container_id: str, endpoint: Path, ready: Path) -> None:
        deadline = time.monotonic() + self.ready_timeout
        while time.monotonic() < deadline:
            if self._status is not None:
                self._poll_status()
            if endpoint.exists() and ready.is_file():
                self._validate_ready(endpoint, ready)
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
                if self._status is not None:
                    self._poll_status()
                raise TaskEnvironmentError(
                    "task environment exited before becoming ready"
                )
            time.sleep(0.05)
        raise TaskEnvironmentError(
            "task environment did not become ready: "
            f"timeout={self.ready_timeout:g}s, container={container_id}, "
            f"socket={endpoint.exists()}, ready={ready.is_file()}"
        )

    def _validate_ready(self, endpoint: Path, ready: Path) -> None:
        try:
            if self._status is None or self._resources is None:
                raise ValueError("missing task environment readiness context")
            if endpoint.is_symlink() or not endpoint.is_socket():
                raise ValueError("task endpoint is not a socket")
            with _regular_file(ready) as stream:
                data = stream.read(4097)
            if len(data) > 4096:
                raise ValueError("task ready marker is too large")
            value = json.loads(data)
            if (
                set(value) != {"run_id", "probes"}
                or value["run_id"] != self._status.run_id
            ):
                raise ValueError("task ready identity mismatch")
            probes = value["probes"]
            if set(probes) != {"candidate", "evidence"}:
                raise ValueError("task mount probes are missing")
            for name, root in (
                ("candidate", self._resources.candidate_root),
                ("evidence", self._resources.evidence_root),
            ):
                probe = probes[name]
                nonce = probe["nonce"]
                if (
                    set(probe) != {"file", "nonce"}
                    or not isinstance(nonce, str)
                    or not re.fullmatch(r"[0-9a-f]{32}", nonce)
                ):
                    raise ValueError("invalid task mount probe")
                if probe["file"] != f".instrbench-probe-{nonce}":
                    raise ValueError("invalid task mount probe path")
                path = root / probe["file"]
                with _regular_file(path) as stream:
                    if stream.read(65) != nonce.encode("ascii"):
                        raise ValueError(f"{name} mount readback failed")
                path.unlink()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(min(1.0, self.ready_timeout))
                connection.connect(str(endpoint))
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            TaskEnvironmentStatusError,
        ) as exc:
            raise TaskEnvironmentError(
                f"task environment readiness failed: {exc}"
            ) from exc

    def _collect_and_remove(self, container_id: str, log_path: Path | None) -> None:
        primary: BaseException | None = None
        try:
            logs = self._run(
                [self.docker_executable, "logs", container_id],
                "collect task environment logs",
                allow_failure=True,
            )
            if log_path is not None:
                if self._last_logs is not None:
                    with log_path.open("wb") as destination:
                        for path in self._last_logs:
                            with path.open("rb") as source:
                                shutil.copyfileobj(source, destination)
                else:
                    log_path.write_text(logs.stdout + logs.stderr, encoding="utf-8")
        except OSError as exc:
            if current_progress():
                current_progress().record_error(exc)
        except BaseException as exc:
            primary = exc
            if current_progress():
                current_progress().record_error(exc)
            raise
        finally:
            try:
                self._run(
                    [self.docker_executable, "rm", "--force", container_id],
                    "remove task environment",
                )
            except BaseException as exc:
                if current_progress():
                    current_progress().record_error(exc)
                if primary is None or isinstance(exc, KeyboardInterrupt):
                    raise

    def _run(
        self, command: list[str], label: str, *, allow_failure: bool = False
    ) -> subprocess.CompletedProcess[str]:
        verb = command[1]
        progress = current_progress()
        names = {
            "build": "构建任务镜像",
            "run": "启动任务容器",
            "stop": "停止任务容器",
            "logs": "保存任务环境日志",
            "rm": "移除任务容器",
        }
        try:
            if self._log_root is None:
                completed = subprocess.run(
                    command,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=2 if verb == "inspect" else 30 if verb != "build" else None,
                )
            else:
                self._command_index += int(verb != "inspect")
                name = (
                    "docker-inspect"
                    if verb == "inspect"
                    else f"docker-{self._command_index:02d}-{verb}"
                )
                stdout_path, stderr_path = (
                    self._log_root / f"{name}-stdout.log",
                    self._log_root / f"{name}-stderr.log",
                )
                if verb != "inspect":
                    operation(names.get(verb, label), logs=[stdout_path, stderr_path])
                sanitize = progress.sanitize if progress else Redactor()
                sanitize.add_environment(os.environ)
                callback = (
                    (
                        lambda line: progress.activity(
                            f"Docker build: {line.strip()[:180]}"
                        )
                    )
                    if progress and verb == "build"
                    else None
                )
                result = stream_process(
                    command,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    timeout=None if verb == "build" else 2 if verb == "inspect" else 30,
                    sanitize=sanitize,
                    on_stdout_line=callback,
                    on_stderr_line=callback,
                )
                self._last_logs = (stdout_path, stderr_path)
                completed = subprocess.CompletedProcess(
                    command, result.returncode, result.stdout, result.stderr
                )
                if result.timed_out:
                    raise TaskEnvironmentError(
                        f"cannot {label}: timeout={2 if verb == 'inspect' else 30}s"
                    )
        except OSError as exc:
            raise TaskEnvironmentError(f"cannot {label}: {exc}") from exc
        if completed.returncode != 0:
            details = completed.stderr.strip() or completed.stdout.strip()
            error = TaskEnvironmentError(
                f"cannot {label}: exit_code={completed.returncode}: {details[-2000:]}"
            )
            if not allow_failure:
                raise error
            if progress and verb != "inspect":
                progress.record_error(error)
        return completed


def source_manifest_path_root(
    tasks_checkout: Path, source_manifest: Mapping[str, Any]
) -> Path:
    return tasks_checkout.resolve() / "sources" / str(source_manifest["source_id"])


def _container_name(run_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "-", run_id)[:36]
    return f"instrbench-task-{safe}-{os.getpid()}-{secrets.token_hex(4)}"
