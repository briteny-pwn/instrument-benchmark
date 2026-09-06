from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from .diagnostics import Redactor
from .progress import current_progress, operation
from .streaming_process import stream_process

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
    error_message: str | None = None

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
            "error_message": self.error_message,
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
        raise AgentInfrastructureError(f"cannot load Agent environment: {exc}") from exc

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
        on_poll: Callable[[], None] | None = None,
    ) -> AgentExecution:
        process_environment = dict(os.environ)
        if environ is not None:
            process_environment.update(environ)
        process_environment.update(settings.environment)
        progress = current_progress()
        sanitize = progress.sanitize if progress is not None else Redactor()
        sanitize.add_environment(process_environment)
        operation("查找 Claude Code 可执行文件")
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

        operation(
            "启动 Claude Code 并读取实时事件",
            logs=[stdout_path, stderr_path],
            model=settings.model,
        )
        tool_ids: set[str] = set()
        error_message: str | None = None

        def observe(line: str) -> None:
            nonlocal error_message
            try:
                event = json.loads(line)
            except (ValueError, TypeError):
                return
            if not isinstance(event, dict):
                return
            if event.get("type") == "assistant":
                message = event.get("message")
                content = (
                    message.get("content", []) if isinstance(message, dict) else []
                )
                for block in content if isinstance(content, list) else []:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        identifier = str(block.get("id", ""))
                        if identifier and identifier not in tool_ids:
                            tool_ids.add(identifier)
                            if progress:
                                progress.activity(
                                    f"工具调用 {str(block.get('name', 'unknown'))[:80]}",
                                    tools=len(tool_ids),
                                )
                    elif block.get("type") == "text" and progress:
                        progress.activity("Agent 消息已接收", tools=len(tool_ids))
            elif event.get("type") == "result":
                if event.get("is_error") is True or str(
                    event.get("subtype", "")
                ).startswith("error"):
                    error_message = str(
                        event.get("errors")
                        or event.get("result")
                        or event.get("subtype")
                        or "Agent result error"
                    )[-2000:]
                if progress:
                    progress.activity("Agent 结果事件已接收", tools=len(tool_ids))
            elif event.get("type") in {"system", "user"} and progress:
                progress.activity(
                    f"Agent {event['type']} 事件已接收", tools=len(tool_ids)
                )

        try:
            result = stream_process(
                command,
                cwd=workspace_path,
                env=process_environment,
                input_text=prompt,
                timeout=self.timeout_seconds,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                on_stdout_line=observe,
                sanitize=sanitize,
                on_poll=on_poll,
                on_stderr_line=(lambda _: progress.activity("Agent stderr 已更新"))
                if progress
                else None,
            )
        except OSError as exc:
            raise AgentInfrastructureError(
                f"cannot execute Claude Code or persist logs: {exc}"
            ) from exc
        if result.timed_out:
            status = "timeout"
            error_message = f"Agent exceeded timeout={self.timeout_seconds:g}s"
        elif result.returncode == 0 and error_message is None:
            status = "completed"
        else:
            status = "failed"
            error_message = (
                error_message
                or result.stderr.strip()[-2000:]
                or f"Agent exit_code={result.returncode}"
            )
        return AgentExecution(
            agent="claudecode",
            model=settings.model,
            isolation="trusted_host",
            status=status,
            exit_code=result.returncode,
            duration_seconds=result.duration_seconds,
            workspace=workspace_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=command,
            error_message=error_message,
        )


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
