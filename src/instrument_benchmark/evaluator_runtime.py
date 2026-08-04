from __future__ import annotations

import hashlib
import json
import os
import secrets
import selectors
import socket
import stat
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable

from .evaluator_image import EvaluatorImageEvidence


REPORT_LIMIT = 16 * 1024 * 1024


class EvaluatorInfrastructureError(RuntimeError):
    def __init__(self, message: str, *, retry_eligible: bool = True):
        self.retry_eligible = retry_eligible
        super().__init__(message)


@dataclass(frozen=True)
class RuntimeCommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class AttachedEvaluatorResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    output_limited: bool


@dataclass(frozen=True)
class EvaluatorContainerEvidence:
    container_id: str
    image_id: str
    image_reference: str
    dockerfile_sha256: str
    build_manifest_sha256: str
    evaluator_commit: str
    created_at: str
    started_at: str
    finished_at: str
    exit_code: int
    oom_killed: bool
    network_mode: str
    readonly_rootfs: bool
    user: str
    group_add: tuple[str, ...]
    cap_drop: tuple[str, ...]
    security_options: tuple[str, ...]
    pids_limit: int
    memory_bytes: int
    memory_swap_bytes: int
    nano_cpus: int
    mounts: tuple[dict[str, object], ...]
    stdout_bytes: int
    stderr_bytes: int
    stdout_sha256: str
    stderr_sha256: str
    report_sha256: str
    cleanup_succeeded: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class EvaluatorContainerResult:
    report: dict[str, object]
    evidence: EvaluatorContainerEvidence
    stdout: str
    stderr: str


RuntimeExecutor = Callable[[list[str]], RuntimeCommandResult]
AttachExecutor = Callable[..., AttachedEvaluatorResult]


class EvaluatorContainerRunner:
    def __init__(
        self,
        *,
        docker_socket: Path = Path("/var/run/docker.sock"),
        docker_executable: str = "docker",
        executor: RuntimeExecutor | None = None,
        attach_executor: AttachExecutor | None = None,
    ) -> None:
        self.docker_socket = docker_socket.resolve()
        self.docker_executable = docker_executable
        self.executor = executor or _execute
        self.attach_executor = attach_executor or _start_attached

    def run(
        self,
        *,
        image: EvaluatorImageEvidence,
        request_path: Path,
        report_path: Path,
        instance_path: Path,
        candidate_path: Path,
        shared_run_root: Path,
        run_id: str,
        timeout: float,
        stdout_limit: int,
        stderr_limit: int,
    ) -> EvaluatorContainerResult:
        paths = _validate_paths(
            request_path=request_path,
            report_path=report_path,
            instance_path=instance_path,
            candidate_path=candidate_path,
            shared_run_root=shared_run_root,
            docker_socket=self.docker_socket,
        )
        name = _container_name(run_id)
        owner = os.environ.get("IAB_CONTAINER_OWNER", run_id)
        socket_gid = self.docker_socket.stat().st_gid
        create = self.executor(
            [
                self.docker_executable,
                "create",
                f"--name={name}",
                "--label=iab.managed=true",
                "--label=iab.kind=evaluator",
                f"--label=iab.owner={owner}",
                f"--label=iab.run_id={run_id}",
                f"--env=IAB_CONTAINER_OWNER={owner}",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--log-driver=none",
                "--user=11001:11001",
                f"--group-add={socket_gid}",
                "--pids-limit=256",
                "--memory=2g",
                "--memory-swap=2g",
                "--cpus=2.0",
                "--stop-timeout=2",
                "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=256m",
                _mount(paths["shared_run_root"], paths["shared_run_root"], False),
                _mount(paths["instance_path"], paths["instance_path"], True),
                _mount(paths["candidate_path"], paths["candidate_path"], True),
                _mount(self.docker_socket, Path("/var/run/docker.sock"), False),
                image.image_id,
                "run",
                "--request",
                str(paths["request_path"]),
                "--report",
                str(paths["report_path"]),
            ]
        )
        _require_success(create, "create evaluator container")
        container_id = create.stdout.strip()
        if not container_id:
            raise EvaluatorInfrastructureError("Docker returned no evaluator container ID")
        removed = False
        try:
            try:
                attached = self.attach_executor(
                    self.docker_executable,
                    container_id,
                    timeout=timeout,
                    stdout_limit=stdout_limit,
                    stderr_limit=stderr_limit,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise EvaluatorInfrastructureError(
                    f"cannot start evaluator container: {exc}"
                ) from exc
            inspected = self.executor(
                [self.docker_executable, "inspect", container_id]
            )
            _require_success(inspected, "inspect evaluator container")
            inspect = _one_inspect(inspected.stdout)
            state = inspect.get("State", {})
            oom = bool(state.get("OOMKilled"))
            if attached.timed_out:
                raise EvaluatorInfrastructureError("evaluator container timed out")
            if attached.output_limited:
                raise EvaluatorInfrastructureError("evaluator container output limit exceeded")
            if oom:
                raise EvaluatorInfrastructureError("evaluator container was OOM killed")
            exit_code = int(state.get("ExitCode", attached.returncode))
            if exit_code != 0 or attached.returncode != 0:
                raise EvaluatorInfrastructureError(
                    f"evaluator container failed with exit code {exit_code}: "
                    f"{attached.stderr.strip()}"
                )
            report, report_sha256 = _collect_report(paths["report_path"])
            evidence = _evidence(
                inspect,
                image,
                attached,
                report_sha256=report_sha256,
                cleanup_succeeded=False,
            )
            _validate_runtime_policy(
                evidence,
                inspect=inspect,
                image=image,
                paths=paths,
                run_id=run_id,
                owner=owner,
                socket_gid=socket_gid,
            )
            removal = self.executor(
                [self.docker_executable, "rm", "--force", container_id]
            )
            _require_success(removal, "remove evaluator container")
            removed = True
            return EvaluatorContainerResult(
                report=report,
                evidence=replace(evidence, cleanup_succeeded=True),
                stdout=attached.stdout,
                stderr=attached.stderr,
            )
        finally:
            if not removed:
                primary_error = sys.exception()
                removal = self.executor(
                    [self.docker_executable, "rm", "--force", container_id]
                )
                if removal.returncode != 0:
                    message = "failed to remove evaluator container: " + (
                        removal.stderr.strip() or removal.stdout.strip()
                    )
                    if primary_error is not None:
                        primary_error.add_note(message)
                    else:
                        raise EvaluatorInfrastructureError(message)


def _validate_paths(**raw: Path) -> dict[str, Path]:
    paths = {name: value.resolve() for name, value in raw.items()}
    shared = paths["shared_run_root"]
    if not shared.is_dir() or shared == Path(shared.anchor):
        raise EvaluatorInfrastructureError("shared run root is invalid")
    if not paths["request_path"].is_file():
        raise EvaluatorInfrastructureError("evaluator request is missing")
    if not paths["instance_path"].is_dir():
        raise EvaluatorInfrastructureError("instance path is invalid")
    if not paths["candidate_path"].is_file():
        raise EvaluatorInfrastructureError("candidate path is invalid")
    if not paths["report_path"].is_relative_to(shared):
        raise EvaluatorInfrastructureError("evaluator report must be below shared root")
    try:
        socket_mode = paths["docker_socket"].stat().st_mode
    except OSError as exc:
        raise EvaluatorInfrastructureError("Docker socket is unavailable") from exc
    if not stat.S_ISSOCK(socket_mode):
        raise EvaluatorInfrastructureError("Docker socket path is not a socket")
    return paths


def _mount(source: Path, destination: Path, readonly: bool) -> str:
    suffix = ",readonly" if readonly else ""
    return (
        "--mount=type=bind,"
        f"src={source.resolve()},dst={destination}{suffix}"
    )


def _collect_report(path: Path) -> tuple[dict[str, object], str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise EvaluatorInfrastructureError(f"cannot open evaluator report: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise EvaluatorInfrastructureError("evaluator report is not a safe regular file")
        if metadata.st_size > REPORT_LIMIT:
            raise EvaluatorInfrastructureError("evaluator report exceeds size limit")
        payload = b""
        while len(payload) <= REPORT_LIMIT:
            chunk = os.read(descriptor, min(65536, REPORT_LIMIT + 1 - len(payload)))
            if not chunk:
                break
            payload += chunk
        if len(payload) > REPORT_LIMIT:
            raise EvaluatorInfrastructureError("evaluator report exceeds size limit")
    finally:
        os.close(descriptor)
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise EvaluatorInfrastructureError("evaluator report is malformed") from exc
    if not isinstance(value, dict):
        raise EvaluatorInfrastructureError("evaluator report must be an object")
    return value, hashlib.sha256(payload).hexdigest()


def _evidence(
    inspect: dict,
    image: EvaluatorImageEvidence,
    attached: AttachedEvaluatorResult,
    *,
    report_sha256: str,
    cleanup_succeeded: bool,
) -> EvaluatorContainerEvidence:
    state = inspect.get("State", {})
    config = inspect.get("Config", {})
    host = inspect.get("HostConfig", {})
    stdout = attached.stdout.encode("utf-8")
    stderr = attached.stderr.encode("utf-8")
    return EvaluatorContainerEvidence(
        container_id=str(inspect.get("Id", "")),
        image_id=image.image_id,
        image_reference=image.reference,
        dockerfile_sha256=image.dockerfile_sha256,
        build_manifest_sha256=image.build_manifest_sha256,
        evaluator_commit=image.evaluator_commit,
        created_at=str(inspect.get("Created", "")),
        started_at=str(state.get("StartedAt", "")),
        finished_at=str(state.get("FinishedAt", "")),
        exit_code=int(state.get("ExitCode", attached.returncode)),
        oom_killed=bool(state.get("OOMKilled")),
        network_mode=str(host.get("NetworkMode", "")),
        readonly_rootfs=bool(host.get("ReadonlyRootfs")),
        user=str(config.get("User", "")),
        group_add=tuple(str(value) for value in host.get("GroupAdd", []) or []),
        cap_drop=tuple(str(value) for value in host.get("CapDrop", []) or []),
        security_options=tuple(str(value) for value in host.get("SecurityOpt", []) or []),
        pids_limit=int(host.get("PidsLimit", 0)),
        memory_bytes=int(host.get("Memory", 0)),
        memory_swap_bytes=int(host.get("MemorySwap", 0)),
        nano_cpus=int(host.get("NanoCpus", 0)),
        mounts=tuple(dict(value) for value in inspect.get("Mounts", []) or []),
        stdout_bytes=len(stdout),
        stderr_bytes=len(stderr),
        stdout_sha256=hashlib.sha256(stdout).hexdigest(),
        stderr_sha256=hashlib.sha256(stderr).hexdigest(),
        report_sha256=report_sha256,
        cleanup_succeeded=cleanup_succeeded,
    )


def _one_inspect(payload: str) -> dict:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise EvaluatorInfrastructureError("Docker inspect returned malformed JSON") from exc
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise EvaluatorInfrastructureError("Docker inspect must return one object")
    return value[0]


def _validate_runtime_policy(
    evidence: EvaluatorContainerEvidence,
    *,
    inspect: dict,
    image: EvaluatorImageEvidence,
    paths: dict[str, Path],
    run_id: str,
    owner: str,
    socket_gid: int,
) -> None:
    mounts = {
        (
            str(value.get("Type", "")),
            str(value.get("Source", "")),
            str(value.get("Destination", "")),
            bool(value.get("RW")),
        )
        for value in evidence.mounts
    }
    expected_mounts = {
        ("bind", str(paths["shared_run_root"]), str(paths["shared_run_root"]), True),
        ("bind", str(paths["instance_path"]), str(paths["instance_path"]), False),
        ("bind", str(paths["candidate_path"]), str(paths["candidate_path"]), False),
        ("bind", str(paths["docker_socket"]), "/var/run/docker.sock", True),
    }
    config = inspect.get("Config", {})
    labels = config.get("Labels", {}) if isinstance(config, dict) else {}
    environment = config.get("Env", []) if isinstance(config, dict) else []
    host = inspect.get("HostConfig", {})
    tmpfs = host.get("Tmpfs", {}) if isinstance(host, dict) else {}
    tmpfs_options = set(str(tmpfs.get("/tmp", "")).split(","))
    checks = (
        inspect.get("Image") == image.image_id,
        labels.get("iab.managed") == "true",
        labels.get("iab.kind") == "evaluator",
        labels.get("iab.owner") == owner,
        labels.get("iab.run_id") == run_id,
        f"IAB_CONTAINER_OWNER={owner}" in environment,
        evidence.network_mode == "none",
        evidence.readonly_rootfs,
        evidence.user == "11001:11001",
        "ALL" in evidence.cap_drop,
        "no-new-privileges" in evidence.security_options,
        evidence.pids_limit == 256,
        evidence.memory_bytes == 2 * 1024**3,
        evidence.memory_swap_bytes == 2 * 1024**3,
        evidence.nano_cpus == 2_000_000_000,
        str(socket_gid) in evidence.group_add,
        mounts == expected_mounts,
        set(tmpfs) == {"/tmp"},
        tmpfs_options
        in (
            {"rw", "noexec", "nosuid", "nodev", "size=268435456"},
            {"rw", "noexec", "nosuid", "nodev", "size=256m"},
        ),
    )
    if not all(checks):
        raise EvaluatorInfrastructureError(
            "evaluator container runtime policy does not match the hardened contract"
        )


def _container_name(run_id: str) -> str:
    safe = "".join(character if character.isalnum() else "-" for character in run_id)
    return f"iab-evaluator-{safe[:48]}-{secrets.token_hex(6)}"


def _require_success(result: RuntimeCommandResult, operation: str) -> None:
    if result.returncode != 0:
        raise EvaluatorInfrastructureError(
            f"{operation} failed: {result.stderr.strip() or result.stdout.strip()}"
        )


def _execute(arguments: list[str]) -> RuntimeCommandResult:
    try:
        completed = subprocess.run(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise EvaluatorInfrastructureError("Docker executable is unavailable") from exc
    return RuntimeCommandResult(completed.returncode, completed.stdout, completed.stderr)


def _start_attached(
    docker_executable: str,
    container_id: str,
    *,
    timeout: float,
    stdout_limit: int,
    stderr_limit: int,
) -> AttachedEvaluatorResult:
    process = subprocess.Popen(
        [docker_executable, "start", "--attach", container_id],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, ("stdout", stdout_limit))
    selector.register(process.stderr, selectors.EVENT_READ, ("stderr", stderr_limit))
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout
    timed_out = False
    output_limited = False
    killed = False
    while selector.get_map():
        remaining = deadline - time.monotonic()
        if remaining <= 0 and not killed:
            timed_out = True
            _kill(docker_executable, container_id)
            killed = True
        for key, _ in selector.select(0.1):
            stream, limit = key.data
            chunk = os.read(key.fileobj.fileno(), 65536)
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            buffer = buffers[stream]
            buffer.extend(chunk[: max(0, limit + 1 - len(buffer))])
            if len(buffer) > limit and not killed:
                output_limited = True
                _kill(docker_executable, container_id)
                killed = True
    returncode = process.wait(timeout=5)
    selector.close()
    process.stdout.close()
    process.stderr.close()
    return AttachedEvaluatorResult(
        returncode=returncode,
        stdout=bytes(buffers["stdout"][:stdout_limit]).decode("utf-8", errors="replace"),
        stderr=bytes(buffers["stderr"][:stderr_limit]).decode("utf-8", errors="replace"),
        timed_out=timed_out,
        output_limited=output_limited,
    )


def _kill(docker_executable: str, container_id: str) -> None:
    completed = subprocess.run(
        [docker_executable, "kill", container_id],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise EvaluatorInfrastructureError(
            "failed to kill evaluator container: "
            + completed.stderr.decode("utf-8", errors="replace").strip()
        )
