from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from instrument_benchmark import cli
from instrument_benchmark.agent import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_AUTH_TOKEN,
    ANTHROPIC_BASE_URL,
    INSTRBENCH_AGENT_MODEL,
    ClaudeCodeRunner,
    load_claude_code_settings,
)
from instrument_benchmark import orchestrator


def _write_fake_claude(bin_directory: Path) -> Path:
    bin_directory.mkdir(parents=True)
    executable = bin_directory / "claude"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import pathlib
import sys

prompt = sys.stdin.read()
if "answer.json" not in prompt:
    raise SystemExit(9)
pathlib.Path("answer.json").write_text('{"answer": 42}\\n')
print(json.dumps({"type": "result", "subtype": "success"}))
""",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def _write_task_repository(root: Path) -> None:
    leaf = root / "sources" / "demo" / "task"
    leaf.mkdir(parents=True)
    (leaf.parent / "source.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "source_id": "demo",
                "display_name": "Demo",
                "description": "Demo task",
                "instances": ["task"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    files = {
        "prompt.md": "Write the final JSON result to `answer.json`.\n",
        "docs/format.md": "The answer must be JSON.\n",
    }
    visible = {}
    for relative, content in files.items():
        path = leaf / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        visible[relative] = hashlib.sha256(content.encode()).hexdigest()
    (leaf / "instance.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "instance_id": "task",
                "source_id": "demo",
                "visible_files": visible,
                "submission": {"filename": "answer.json"},
                "evaluator": {"id": "evaluator", "protocol_version": 2},
                "container": {"protocol_version": 1},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_evaluator_repository(root: Path) -> None:
    leaf = root / "sources" / "demo" / "evaluator"
    leaf.mkdir(parents=True)
    (leaf.parent / "source.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "source_id": "demo",
                "display_name": "Demo",
                "description": "Demo evaluator",
                "evaluators": ["evaluator"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (leaf / "evaluator.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "source_id": "demo",
                "evaluator_id": "evaluator",
                "protocol_version": 2,
                "container_protocol_version": 1,
                "candidate_execution": "docker",
                "image_mode": "locked",
                "supported_instances": ["task"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


@pytest.mark.smoke
def test_cli_agent_suite_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    instrument = tmp_path / "instrument"
    tasks = tmp_path / "tasks"
    evaluator = tmp_path / "evaluator"
    instrument.mkdir()
    evaluator.mkdir()
    _write_task_repository(tasks)
    _write_evaluator_repository(evaluator)
    fake_bin = tmp_path / "bin"
    _write_fake_claude(fake_bin)
    monkeypatch.setenv("INSTANCES_REPO_PATH", str(tasks))
    monkeypatch.setenv("EVALUATOR_REPO_PATH", str(evaluator))
    monkeypatch.setenv(
        "PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", "")
    )
    (instrument / ".env").write_text(
        f"INSTANCES_REPO_PATH={tasks}\n"
        f"EVALUATOR_REPO_PATH={evaluator}\n"
        f"{INSTRBENCH_AGENT_MODEL}=smoke-model\n"
        f"{ANTHROPIC_BASE_URL}=https://gateway.example.test\n"
        f"{ANTHROPIC_AUTH_TOKEN}=smoke-secret\n",
        encoding="utf-8",
    )
    run_path = tmp_path / "configs" / "run.yaml"
    run_path.parent.mkdir()
    run_report = tmp_path / "reports" / "run.json"
    run_path.write_text(
        yaml.safe_dump(
            {
                "run_id": "smoke-run",
                "source_id": "demo",
                "instance_id": "task",
                "evaluator_id": "evaluator",
                "report_path": str(run_report),
                "timeout_seconds": 30,
                "max_output_bytes": 1024,
                "repeated_worlds": 1,
                "repeated_base_seed": 1,
                "container_protocol_version": 1,
                "image_mode": "locked",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    suite_path = tmp_path / "suites" / "smoke.yaml"
    suite_path.parent.mkdir()
    suite_report = tmp_path / "reports" / "suite.json"
    suite_path.write_text(
        yaml.safe_dump(
            {
                "suite_id": "smoke",
                "agent": "claudecode",
                "runs": [str(run_path)],
                "result_path": str(suite_report),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    def fake_evaluator(config_path: Path, **kwargs: object) -> dict[str, object]:
        candidate = Path(kwargs["candidate_path"])
        assert candidate.name == "answer.json"
        assert json.loads(candidate.read_text()) == {"answer": 42}
        return {"status": "completed", "score": 100.0, "strict_pass": True}

    with (
        patch.object(cli, "ROOT", instrument),
        patch.object(orchestrator, "run_benchmark", fake_evaluator),
    ):
        exit_status = cli.main(["run", "--suite", str(suite_path)])

    assert exit_status == 0
    output = json.loads(capsys.readouterr().out)
    assert output["report"] == str(suite_report)
    assert output["summary"]["generated"] == 1
    assert output["summary"]["evaluated"] == 1
    report = json.loads(run_report.read_text())
    assert report["agent_execution"]["agent"] == "claudecode"
    assert report["agent_execution"]["model"] == "smoke-model"
    assert report["agent_execution"]["isolation"] == "trusted_host"
    assert report["agent_execution"]["candidate_path"].endswith("answer.json")
    assert "smoke-secret" not in run_report.read_text()


@pytest.mark.smoke
def test_real_claude_code_can_create_manifest_named_candidate(
    tmp_path: Path,
) -> None:
    if os.environ.get("INSTRBENCH_RUN_REAL_AGENT_TESTS") != "1":
        pytest.skip("real Claude Code smoke is opt-in")
    if shutil.which("claude") is None:
        pytest.skip("claude executable is unavailable")
    required = [INSTRBENCH_AGENT_MODEL, ANTHROPIC_BASE_URL]
    if any(not os.environ.get(name) for name in required) or not (
        os.environ.get(ANTHROPIC_AUTH_TOKEN) or os.environ.get(ANTHROPIC_API_KEY)
    ):
        pytest.skip("real Claude Code environment is incomplete")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = load_claude_code_settings(tmp_path)
    execution = ClaudeCodeRunner(timeout_seconds=180).run(
        settings=settings,
        prompt=(
            "Create a file named smoke-answer.txt in the current working directory "
            "whose complete content is the word ok followed by a newline."
        ),
        workspace=workspace,
        artifacts_root=tmp_path / "artifacts",
    )

    assert execution.status == "completed"
    assert (workspace / "smoke-answer.txt").read_text() == "ok\n"
