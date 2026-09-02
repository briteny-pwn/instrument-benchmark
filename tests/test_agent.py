from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from instrument_benchmark.agent import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_AUTH_TOKEN,
    ANTHROPIC_BASE_URL,
    INSTRBENCH_AGENT_MODEL,
    AgentInfrastructureError,
    ClaudeCodeRunner,
    load_claude_code_settings,
)


def _environment(**updates: str) -> dict[str, str]:
    value = {
        INSTRBENCH_AGENT_MODEL: "gateway-model",
        ANTHROPIC_BASE_URL: "https://gateway.example.test",
        ANTHROPIC_AUTH_TOKEN: "secret-token",
    }
    value.update(updates)
    return value


def _write_executable(directory: Path, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    executable = directory / "claude"
    executable.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def test_loads_agent_settings_from_repository_dotenv(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        f"{INSTRBENCH_AGENT_MODEL}=dotenv-model\n"
        f"{ANTHROPIC_BASE_URL}=https://dotenv.example.test\n"
        f"{ANTHROPIC_API_KEY}=dotenv-secret\n",
        encoding="utf-8",
    )

    settings = load_claude_code_settings(tmp_path, environ={})

    assert settings.model == "dotenv-model"
    assert settings.environment[ANTHROPIC_BASE_URL] == "https://dotenv.example.test"
    assert settings.environment[ANTHROPIC_API_KEY] == "dotenv-secret"
    assert "dotenv-secret" not in repr(settings)


def test_process_agent_settings_override_dotenv(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        f"{INSTRBENCH_AGENT_MODEL}=dotenv-model\n"
        f"{ANTHROPIC_BASE_URL}=https://dotenv.example.test\n"
        f"{ANTHROPIC_AUTH_TOKEN}=dotenv-secret\n",
        encoding="utf-8",
    )

    settings = load_claude_code_settings(tmp_path, environ=_environment())

    assert settings.model == "gateway-model"
    assert settings.environment[ANTHROPIC_BASE_URL] == "https://gateway.example.test"
    assert settings.environment[ANTHROPIC_AUTH_TOKEN] == "secret-token"


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({}, INSTRBENCH_AGENT_MODEL),
        (_environment(**{INSTRBENCH_AGENT_MODEL: ""}), INSTRBENCH_AGENT_MODEL),
        (
            {
                INSTRBENCH_AGENT_MODEL: "model",
                ANTHROPIC_AUTH_TOKEN: "token",
            },
            ANTHROPIC_BASE_URL,
        ),
        (
            {
                INSTRBENCH_AGENT_MODEL: "model",
                ANTHROPIC_BASE_URL: "https://gateway.example.test",
            },
            "ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY",
        ),
    ],
)
def test_rejects_incomplete_agent_environment(
    tmp_path: Path, environment: dict[str, str], message: str
) -> None:
    with pytest.raises(AgentInfrastructureError, match=message):
        load_claude_code_settings(tmp_path, environ=environment)


def test_runs_claude_code_with_prompt_model_environment_and_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    fake_bin = tmp_path / "bin"
    executable = _write_executable(
        fake_bin,
        """import json
import os
import pathlib
import sys

pathlib.Path("invocation.json").write_text(json.dumps({
    "arguments": sys.argv[1:],
    "prompt": sys.stdin.read(),
    "cwd": os.getcwd(),
    "model_environment": os.environ["INSTRBENCH_AGENT_MODEL"],
    "base_url": os.environ["ANTHROPIC_BASE_URL"],
}))
print(json.dumps({"type": "result", "subtype": "success"}))
""",
    )
    process_environment = _environment(
        PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", "")
    )
    settings = load_claude_code_settings(tmp_path, environ=process_environment)

    execution = ClaudeCodeRunner().run(
        settings=settings,
        prompt="Create the candidate.\n",
        workspace=workspace,
        artifacts_root=tmp_path / "artifacts",
        environ=process_environment,
    )

    invocation = json.loads((workspace / "invocation.json").read_text())
    assert invocation == {
        "arguments": [
            "-p",
            "--model",
            "gateway-model",
            "--output-format",
            "stream-json",
            "--verbose",
        ],
        "prompt": "Create the candidate.\n",
        "cwd": str(workspace),
        "model_environment": "gateway-model",
        "base_url": "https://gateway.example.test",
    }
    assert execution.agent == "claudecode"
    assert execution.model == "gateway-model"
    assert execution.isolation == "trusted_host"
    assert execution.status == "completed"
    assert execution.exit_code == 0
    assert execution.workspace == workspace.resolve()
    assert execution.stdout_path.read_text().startswith('{"type": "result"')
    assert execution.stderr_path.read_text() == ""
    assert execution.command[0] == str(executable)
    metadata = execution.to_dict()
    assert metadata["workspace"] == str(workspace.resolve())
    assert metadata["isolation"] == "trusted_host"
    assert "secret-token" not in json.dumps(metadata)


def test_records_nonzero_agent_exit(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    fake_bin = tmp_path / "bin"
    _write_executable(fake_bin, "import sys\nsys.exit(7)\n")
    environment = _environment(
        PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", "")
    )
    settings = load_claude_code_settings(tmp_path, environ=environment)

    execution = ClaudeCodeRunner().run(
        settings=settings,
        prompt="prompt",
        workspace=workspace,
        artifacts_root=tmp_path / "artifacts",
        environ=environment,
    )

    assert execution.status == "failed"
    assert execution.exit_code == 7


def test_times_out_process_group_and_preserves_partial_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    fake_bin = tmp_path / "bin"
    _write_executable(
        fake_bin,
        """import pathlib
import time

pathlib.Path("answer.json").write_text("{}\\n")
time.sleep(60)
""",
    )
    environment = _environment(
        PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", "")
    )
    settings = load_claude_code_settings(tmp_path, environ=environment)

    execution = ClaudeCodeRunner(timeout_seconds=0.5).run(
        settings=settings,
        prompt="prompt",
        workspace=workspace,
        artifacts_root=tmp_path / "artifacts",
        environ=environment,
    )

    assert execution.status == "timeout"
    assert execution.duration_seconds < 5
    assert (workspace / "answer.json").is_file()


def test_requires_claude_executable(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    environment = _environment(PATH=str(tmp_path / "empty-bin"))
    settings = load_claude_code_settings(tmp_path, environ=environment)

    with pytest.raises(AgentInfrastructureError, match="claude executable"):
        ClaudeCodeRunner().run(
            settings=settings,
            prompt="prompt",
            workspace=workspace,
            artifacts_root=tmp_path / "artifacts",
            environ=environment,
        )
