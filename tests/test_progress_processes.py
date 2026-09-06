from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from test_agent import _environment, _write_executable

from instrument_benchmark.agent import ClaudeCodeRunner, load_claude_code_settings
from instrument_benchmark.progress import ProgressReporter


def test_agent_streams_activity_and_sanitized_logs_before_exit(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    fake_bin = tmp_path / "bin"
    logs = tmp_path / "logs"
    # Child waits for the parent callback to write a marker. Buffer-at-exit cannot pass.
    _write_executable(
        fake_bin,
        """import json, pathlib, time, sys
sys.stdin.read()
print(json.dumps({"type":"assistant", "message":{"content":[{"type":"tool_use", "id":"one", "name":"Bash", "input":{"command":"secret-token"}}]}}), flush=True)
deadline = time.monotonic() + 2
while not pathlib.Path("observed").exists() and time.monotonic() < deadline:
    time.sleep(.01)
sys.exit(0 if pathlib.Path("observed").exists() else 9)
""",
    )
    environment = _environment(PATH=str(fake_bin) + os.pathsep + os.environ["PATH"])
    settings = load_claude_code_settings(tmp_path, environ=environment)

    class ObservingProgress(ProgressReporter):
        def activity(self, message, **details):
            super().activity(message, **details)
            if "Bash" in message:
                assert (logs / "agent-output.jsonl").is_file()
                (workspace / "observed").touch()

    stream = io.StringIO()
    with ObservingProgress(stream=stream) as progress:
        progress.start_run("r", "s", "t")
        result = ClaudeCodeRunner(timeout_seconds=3).run(
            settings=settings,
            prompt="do work",
            workspace=workspace,
            artifacts_root=logs,
            environ=environment,
        )
    assert result.exit_code == 0
    assert "Bash" in stream.getvalue()
    assert "secret-token" not in stream.getvalue()
    assert "secret-token" not in result.stdout_path.read_text()


def test_agent_error_event_is_reported_even_with_zero_exit(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    fake_bin = tmp_path / "bin"
    _write_executable(
        fake_bin,
        'print(\'{"type":"result","is_error":true,"errors":["authentication failed"]}\')\n',
    )
    environment = _environment(PATH=str(fake_bin) + os.pathsep + os.environ["PATH"])
    result = ClaudeCodeRunner().run(
        settings=load_claude_code_settings(tmp_path, environ=environment),
        prompt="p",
        workspace=workspace,
        artifacts_root=tmp_path / "logs",
        environ=environment,
    )
    assert result.status == "failed"
    assert "authentication failed" in result.error_message


def test_evaluator_nonzero_error_points_to_real_logs(tmp_path: Path) -> None:
    from instrument_benchmark.evaluator_process import (
        EvaluatorProcessError,
        HostSourceEvaluatorRunner,
    )

    evaluator = tmp_path / "evaluator"
    package = evaluator / "instrument_benchmark_evaluator"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "cli.py").write_text(
        "import sys\nprint('scorer exploded', file=sys.stderr)\nsys.exit(7)\n"
    )
    stream = io.StringIO()
    with ProgressReporter(stream=stream) as progress:
        progress.start_run("r", "s", "t")
        with pytest.raises(EvaluatorProcessError):
            with progress.stage("evaluate"):
                HostSourceEvaluatorRunner().evaluate(
                    evaluator_checkout=evaluator,
                    request={"source_id": "s"},
                    artifacts_root=tmp_path / "artifacts",
                )
    assert "exit_code=7" in stream.getvalue()
    assert "scorer exploded" in stream.getvalue()
    assert (
        str(tmp_path / "artifacts/evaluator-stderr.log")
        in progress.diagnostics[0]["logs"]
    )


def test_docker_build_failure_has_exit_code_stage_and_saved_logs(
    tmp_path: Path,
) -> None:
    import yaml
    from test_source_routed_pipeline import _fixture

    from instrument_benchmark.task_environment import (
        DockerTaskEnvironmentRunner,
        TaskEnvironmentError,
    )

    _, repos, _, _ = _fixture(tmp_path)
    fake_bin = tmp_path / "bin"
    executable = _write_executable(
        fake_bin, "import sys\nprint('build exploded', file=sys.stderr)\nsys.exit(17)\n"
    )
    source = repos.instances_repo_path / "sources/demo"
    stream = io.StringIO()
    with ProgressReporter(stream=stream) as progress:
        progress.start_run("r", "demo", "task")
        with pytest.raises(TaskEnvironmentError):
            with progress.stage("environment"):
                DockerTaskEnvironmentRunner(docker_executable=str(executable)).start(
                    tasks_checkout=repos.instances_repo_path,
                    source_manifest=yaml.safe_load(
                        (source / "source.yaml").read_text()
                    ),
                    instance_root=source / "task",
                    instance_manifest={},
                    run_root=tmp_path / "run",
                    run_id="r",
                )
    assert "exit_code=17" in stream.getvalue()
    assert "构建任务镜像" in progress.diagnostics[0]["step"]
    assert any(
        Path(path).read_text().strip() == "build exploded"
        for path in progress.diagnostics[0]["logs"]
    )


def test_task_start_preserves_readiness_error_when_remove_fails(tmp_path: Path) -> None:
    import yaml
    from test_source_routed_pipeline import _fixture
    from test_task_environment_runner import RecordingRunner

    _, repos, _, _ = _fixture(tmp_path)
    source = repos.instances_repo_path / "sources/demo"

    class Runner(RecordingRunner):
        def _wait_ready(self, *args):
            raise ValueError("readiness failed")

    with ProgressReporter(stream=io.StringIO()) as progress:
        progress.start_run("r", "s", "t")
        with pytest.raises(ValueError, match="readiness failed"):
            with progress.stage("environment"):
                Runner(fail_remove=True).start(
                    tasks_checkout=repos.instances_repo_path,
                    source_manifest=yaml.safe_load(
                        (source / "source.yaml").read_text()
                    ),
                    instance_root=source / "task",
                    instance_manifest={},
                    run_root=tmp_path / "run",
                    run_id="r",
                )
    assert "readiness failed" in progress.diagnostics[0]["error"]
    assert any("remove" in entry["error"] for entry in progress.diagnostics)
