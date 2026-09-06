from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
from test_agent import _write_executable
from test_source_routed_pipeline import AGENT_ENVIRONMENT, _fixture

from instrument_benchmark import cli


def prepare_cli(tmp_path: Path, monkeypatch):
    instrument, repos, config, report = _fixture(tmp_path)
    source_path = repos.instances_repo_path / "sources/demo/source.yaml"
    source = yaml.safe_load(source_path.read_text())
    source["candidate"] = {"producer": "agent", "files": ["solution.py"]}
    source.pop("task_environment")
    source_path.write_text(yaml.safe_dump(source, sort_keys=False))
    executable = _write_executable(
        tmp_path / "bin",
        """import json, pathlib, sys
sys.stdin.read()
print(json.dumps({"type":"assistant","message":{"content":[{"type":"tool_use","id":"1","name":"Write"}]}}), flush=True)
pathlib.Path("solution.py").write_text("answer=42\\n")
print(json.dumps({"type":"result","subtype":"success"}), flush=True)
""",
    )
    package = repos.evaluator_repo_path / "instrument_benchmark_evaluator"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "cli.py").write_text("""import sys, json, pathlib
request=json.loads(pathlib.Path(sys.argv[sys.argv.index("--request")+1]).read_text())
report={key: request[key] for key in ("run_id", "source_id", "instance_id")}
report.update(score=100, evaluator_strict_pass=True, status="completed")
pathlib.Path(sys.argv[sys.argv.index("--report")+1]).write_text(json.dumps(report))
""")
    monkeypatch.setattr(cli, "ROOT", instrument)
    for name, value in {
        **AGENT_ENVIRONMENT,
        "INSTANCES_REPO_PATH": str(repos.instances_repo_path),
        "EVALUATOR_REPO_PATH": str(repos.evaluator_repo_path),
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PATH", str(executable.parent) + os.pathsep + os.environ["PATH"])
    return instrument, repos, config, report


def test_single_cli_streams_progress_without_polluting_json(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _, _, config, report = prepare_cli(tmp_path, monkeypatch)
    assert cli.main(["run", "--config", str(config)]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "report": str(report),
        "score": 100,
        "strict_pass": True,
    }
    assert "① 配置与输入检查" in output.err
    assert "⑧ 报告保存" in output.err
    assert "工具调用 Write" in output.err
    assert "任务：demo/task (run_id=run-1)" in output.err
    assert "跳过" in output.err
    assert "\r" not in output.err and "\x1b" not in output.err
    assert "secret" not in output.err


def test_suite_cli_streams_total_progress_and_keeps_json(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    prepare_cli(tmp_path, monkeypatch)
    suite = tmp_path / "suite.yaml"
    suite.write_text(
        "suite_id: example\nagent: claudecode\nruns: [run.yaml]\nresult_path: suite.json\n"
    )
    assert cli.main(["run", "--suite", str(suite)]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["summary"]["strict_pass"] is True
    assert "Suite example" in output.err and "1/1 已结束" in output.err


def test_cli_configuration_failure_has_only_four_error_fields(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _, _, config, _ = prepare_cli(tmp_path, monkeypatch)
    monkeypatch.setenv("INSTANCES_REPO_PATH", "relative/path")
    assert cli.main(["run", "--config", str(config)]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert all(
        label in output.err for label in ("任务：", "步骤：", "错误：", "日志：")
    )
    assert "INSTANCES_REPO_PATH" in output.err
    assert "建议" not in output.err and "后续动作" not in output.err


def test_cli_interrupt_returns_130_without_traceback(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    _, _, config, _ = prepare_cli(tmp_path, monkeypatch)

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli, "run_benchmark", interrupt)
    assert cli.main(["run", "--config", str(config)]) == 130
    output = capsys.readouterr()
    assert "KeyboardInterrupt" in output.err
    assert "Traceback" not in output.err and output.out == ""


def test_invalid_evaluator_report_is_infrastructure_error(
    tmp_path, monkeypatch, capsys
):
    _, repos, config, _ = prepare_cli(tmp_path, monkeypatch)
    evaluator = repos.evaluator_repo_path / "instrument_benchmark_evaluator/cli.py"
    evaluator.write_text(evaluator.read_text().replace("score=100", "score=-1"))
    assert cli.main(["run", "--config", str(config)]) == 3
    output = capsys.readouterr()
    assert output.out == ""
    assert "score must be between" in output.err
    assert "Evaluator" in output.err


def test_broken_progress_terminal_does_not_abort_scoring(tmp_path, monkeypatch, capsys):
    import io
    import sys

    _, _, config, _ = prepare_cli(tmp_path, monkeypatch)

    class BrokenTerminal(io.StringIO):
        def isatty(self):
            return True

        def write(self, text):
            raise OSError("terminal disconnected")

    monkeypatch.setattr(sys, "stderr", BrokenTerminal())
    assert cli.main(["run", "--config", str(config)]) == 0
    assert json.loads(capsys.readouterr().out)["score"] == 100


def test_initial_config_identity_cannot_inject_terminal_controls(
    tmp_path, monkeypatch, capsys
):
    prepare_cli(tmp_path, monkeypatch)
    monkeypatch.setenv("INSTANCES_REPO_PATH", "relative/path")
    config = tmp_path / "config\x1b[2J\nforged-line.yaml"

    assert cli.main(["run", "--config", str(config)]) == 2

    output = capsys.readouterr()
    assert "\x1b" not in output.err
    assert "\nforged-line" not in output.err
    assert r"\nforged-line.yaml" in output.err
