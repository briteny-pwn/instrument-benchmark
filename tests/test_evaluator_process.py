from __future__ import annotations

import json
import subprocess
from pathlib import Path

from instrument_benchmark.evaluator_process import HostSourceEvaluatorRunner


def test_evaluator_subprocess_does_not_receive_agent_credentials(
    tmp_path: Path, monkeypatch
) -> None:
    evaluator = tmp_path / "evaluator"
    evaluator.mkdir()
    captured: dict[str, object] = {}

    def run(command, **kwargs):
        captured["environment"] = kwargs["env"]
        report_path = Path(command[command.index("--report") + 1])
        report_path.write_text(json.dumps({"score": 1.0}))
        return subprocess.CompletedProcess(command, 0, "", "")

    for name in (
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "INSTRBENCH_AGENT_MODEL",
    ):
        monkeypatch.setenv(name, "secret")
    monkeypatch.setattr("instrument_benchmark.evaluator_process.subprocess.run", run)

    HostSourceEvaluatorRunner().evaluate(
        evaluator_checkout=evaluator,
        request={"source_id": "demo"},
        artifacts_root=tmp_path / "artifacts",
    )

    environment = captured["environment"]
    assert isinstance(environment, dict)
    assert not {
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "INSTRBENCH_AGENT_MODEL",
    } & set(environment)
