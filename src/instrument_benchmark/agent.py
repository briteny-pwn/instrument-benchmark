from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import dotenv_values


INSTRBENCH_AGENT_MODEL = "INSTRBENCH_AGENT_MODEL"
ANTHROPIC_BASE_URL = "ANTHROPIC_BASE_URL"
ANTHROPIC_AUTH_TOKEN = "ANTHROPIC_AUTH_TOKEN"
ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"


class AgentInfrastructureError(RuntimeError):
    """The host environment cannot execute the selected Agent."""


@dataclass(frozen=True)
class ClaudeCodeSettings:
    model: str
    environment: dict[str, str] = field(repr=False)


@dataclass(frozen=True)
class AgentExecution:
    agent: str
    model: str
    isolation: str
    status: str
    exit_code: int | None
    duration_seconds: float
    workspace: Path
    stdout_path: Path
    stderr_path: Path
    command: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "model": self.model,
            "isolation": self.isolation,
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_seconds": self.duration_seconds,
            "workspace": str(self.workspace),
            "stdout_path": str(self.stdout_path),
            "stderr_path": str(self.stderr_path),
            "command": list(self.command),
        }


def load_claude_code_settings(
    instrument_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> ClaudeCodeSettings:
    process = os.environ if environ is None else environ
    try:
        dotenv = dotenv_values(instrument_root.resolve() / ".env")
    except OSError as exc:
        raise AgentInfrastructureError(
            f"cannot load Agent environment: {exc}"
        ) from exc

    model = _required(INSTRBENCH_AGENT_MODEL, process, dotenv)
    base_url = _required(ANTHROPIC_BASE_URL, process, dotenv)
    token = _optional(ANTHROPIC_AUTH_TOKEN, process, dotenv)
    api_key = _optional(ANTHROPIC_API_KEY, process, dotenv)
    if token is None and api_key is None:
        raise AgentInfrastructureError(
            "ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY is required"
        )

    child_environment = {
        INSTRBENCH_AGENT_MODEL: model,
        ANTHROPIC_BASE_URL: base_url,
    }
    if token is not None:
        child_environment[ANTHROPIC_AUTH_TOKEN] = token
    if api_key is not None:
        child_environment[ANTHROPIC_API_KEY] = api_key
    return ClaudeCodeSettings(model=model, environment=child_environment)


class ClaudeCodeRunner:
    def __init__(self, timeout_seconds: float = 1800) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def run(
        self,
        *,
        settings: ClaudeCodeSettings,
        prompt: str,
        workspace: Path,
        artifacts_root: Path,
        environ: Mapping[str, str] | None = None,
    ) -> AgentExecution:
        process_environment = dict(os.environ)
        if environ is not None:
            process_environment.update(environ)
        process_environment.update(settings.environment)
        executable = shutil.which("claude", path=process_environment.get("PATH"))
        if executable is None:
            raise AgentInfrastructureError("claude executable was not found on PATH")

        workspace_path = workspace.resolve()
        if not workspace_path.is_dir():
            raise AgentInfrastructureError("Agent workspace must be a directory")
        artifacts = artifacts_root.resolve()
        try:
            artifacts.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise AgentInfrastructureError(
                f"cannot create Agent artifacts directory: {exc}"
            ) from exc
        stdout_path = artifacts / "agent-output.jsonl"
        stderr_path = artifacts / "agent-stderr.log"
        command = (
            executable,
            "-p",
            "--model",
            settings.model,
            "--output-format",
            "stream-json",
            "--verbose",
        )

        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                cwd=workspace_path,
                env=process_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except OSError as exc:
            raise AgentInfrastructureError(f"cannot start Claude Code: {exc}") from exc

        timed_out = False
        try:
            stdout, stderr = process.communicate(
                input=prompt,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_process_group(process)
            stdout, stderr = process.communicate()
        duration = time.monotonic() - started
        try:
            stdout_path.write_text(stdout or "", encoding="utf-8")
            stderr_path.write_text(stderr or "", encoding="utf-8")
        except OSError as exc:
            raise AgentInfrastructureError(f"cannot write Agent logs: {exc}") from exc

        if timed_out:
            status = "timeout"
        elif process.returncode == 0:
            status = "completed"
        else:
            status = "failed"
        return AgentExecution(
            agent="claudecode",
            model=settings.model,
            isolation="trusted_host",
            status=status,
            exit_code=process.returncode,
            duration_seconds=duration,
            workspace=workspace_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=command,
        )


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return


def _required(
    name: str,
    process: Mapping[str, str],
    dotenv: Mapping[str, str | None],
) -> str:
    value = process[name] if name in process else dotenv.get(name)
    if value is None:
        raise AgentInfrastructureError(f"{name} is required")
    if not value.strip():
        raise AgentInfrastructureError(f"{name} must not be blank")
    return value


def _optional(
    name: str,
    process: Mapping[str, str],
    dotenv: Mapping[str, str | None],
) -> str | None:
    value = process[name] if name in process else dotenv.get(name)
    if value is None or not value.strip():
        return None
    return value
