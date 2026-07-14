from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class AgentInvocation:
    command: list[str]
    stdin: str


class AgentAdapter(Protocol):
    def invocation(self, workspace: Path, model: str) -> AgentInvocation: ...


class ClaudeAdapter:
    def invocation(self, workspace: Path, model: str) -> AgentInvocation:
        prompt = (workspace / "prompt.md").read_text(encoding="utf-8")
        instruction = (
            "Work only in /workspace. Read the instrument documents under /workspace/environment, "
            "complete the task below, and leave the final implementation at /workspace/solution.py.\n\n"
        )
        return AgentInvocation(
            command=[
                "claude", "--bare", "--no-session-persistence", "--print", "--verbose",
                "--input-format", "text", "--output-format", "stream-json",
                "--permission-mode", "bypassPermissions", "--allowedTools", "Read", "Write", "Edit", "Bash",
                "--model", model,
            ],
            stdin=instruction + prompt,
        )


def get_adapter(name: str) -> AgentAdapter:
    if name == "claude":
        return ClaudeAdapter()
    raise ValueError(f"unsupported agent adapter: {name}")
