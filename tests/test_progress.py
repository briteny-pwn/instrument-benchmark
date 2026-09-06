from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest


def test_diagnostics_redact_credentials_and_terminal_controls() -> None:
    from instrument_benchmark.diagnostics import Redactor

    clean = Redactor(["configured-secret"])
    value = clean(
        "configured-secret Authorization: Bearer abc123\n"
        "https://user:password@host/path?api_key=hidden\x1b[2J\x00"
    )
    for secret in ("configured-secret", "abc123", "password", "hidden", "\x1b", "\x00"):
        assert secret not in value
    assert "[REDACTED]" in value


def test_non_tty_progress_persists_events_and_only_four_error_fields(
    tmp_path: Path,
) -> None:
    from instrument_benchmark.progress import ProgressReporter

    stream = io.StringIO()
    log = tmp_path / "agent.log"
    log.write_text("failure")
    with ProgressReporter(stream=stream, secrets=["my-secret"]) as progress:
        progress.start_suite("example", 2)
        progress.start_run("run-1", "demo", "task")
        progress.attach(tmp_path)
        with pytest.raises(RuntimeError):
            with progress.stage("agent"):
                progress.operation(
                    "启动 Claude Code", logs=[log, tmp_path / "absent.log"]
                )
                raise RuntimeError("my-secret failed")
        progress.finish_run(failed=True)
    error = progress.diagnostics[0]
    assert set(error) == {"task", "step", "error", "logs"}
    assert "demo/task" in error["task"] and "run-1" in error["task"]
    assert "启动 Claude Code" in error["step"]
    assert error["logs"] == [
        str(log.resolve()),
        str((tmp_path / "progress.jsonl").resolve()),
    ]
    output = stream.getvalue()
    assert all(label in output for label in ("任务：", "步骤：", "错误：", "日志："))
    assert all(
        label not in output for label in ("建议", "后续动作", "my-secret", "\r", "\x1b")
    )
    events = [
        json.loads(line)
        for line in (tmp_path / "progress.jsonl").read_text().splitlines()
    ]
    assert any(event["event"] == "error" for event in events)
    assert "my-secret" not in json.dumps(events)
    assert "infrastructure_failed=1" in output


def test_candidate_observation_is_provisional_grouped_and_non_mutating(
    tmp_path: Path,
) -> None:
    from instrument_benchmark.candidate import CandidateContract
    from instrument_benchmark.progress import ProgressReporter

    root = tmp_path / "candidate"
    contract = CandidateContract("task_environment", ("step_1/a.stl", "step_2/a.stl"))
    stream = io.StringIO()
    with ProgressReporter(stream=stream, refresh_interval=0.02) as progress:
        progress.start_run("r", "demo", "t")
        progress.watch_candidates(root, contract, groups=("step_1", "step_2"))
        progress.tick()
        assert not root.exists()
        (root / "step_1").mkdir(parents=True)
        (root / "step_1/a.stl").write_text("mesh")
        progress.tick()
        assert progress.candidate_status["present"] == 1
        assert progress.candidate_status["groups"]["step_1"] == [1, 1]
        outside = tmp_path / "outside.stl"
        outside.write_text("private")
        (root / "step_2").mkdir()
        (root / "step_2/a.stl").symlink_to(outside)
        progress.tick()
        assert progress.candidate_status["present"] == 1
    assert "待最终校验" in stream.getvalue()
    assert "step_1=1/1" in stream.getvalue()


def test_primary_error_is_not_replaced_by_cleanup_diagnostic(tmp_path: Path) -> None:
    from instrument_benchmark.progress import ProgressReporter

    with ProgressReporter() as progress:
        progress.start_run("r", "s", "i")
        progress.attach(tmp_path)
        primary = RuntimeError("agent failed")
        with progress.stage("agent"):
            first = progress.record_error(primary)
        with progress.stage("cleanup"):
            progress.record_error(OSError("remove failed"))
        assert progress.record_error(primary) == first
    assert len(progress.diagnostics) == 2
    assert "agent failed" in progress.diagnostics[0]["error"]
    assert "remove failed" in progress.diagnostics[1]["error"]


class TtyStream(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_tty_heartbeat_refreshes_while_stage_has_no_events() -> None:
    from instrument_benchmark.progress import ProgressReporter

    stream = TtyStream()
    with ProgressReporter(stream=stream, refresh_interval=0.02) as progress:
        progress.start_suite("suite", 1)
        progress.start_run("run", "demo", "task")
        with progress.stage("agent"):
            progress.activity("工具调用 Bash", tools=1)
            before = len(stream.getvalue())
            time.sleep(0.09)
            assert len(stream.getvalue()) > before
        progress.finish_run(report={"score": 100, "strict_pass": True})
    assert "距最近事件" in stream.getvalue()
    assert "1/1" in stream.getvalue()
    assert not any(
        t.name == "instrbench-progress" and t.is_alive()
        for t in __import__("threading").enumerate()
    )


def test_progress_context_is_restored_after_failure() -> None:
    from instrument_benchmark.progress import ProgressReporter, current_progress

    assert current_progress() is None
    with pytest.raises(ValueError):
        with ProgressReporter() as progress:
            assert current_progress() is progress
            raise ValueError("failure")
    assert current_progress() is None


def test_diagnostic_without_log_directory_does_not_invent_a_path(
    tmp_path: Path,
) -> None:
    from instrument_benchmark.progress import ProgressReporter

    blocked = tmp_path / "not-a-directory"
    blocked.write_text("data")
    stream = io.StringIO()
    with ProgressReporter(stream=stream) as progress:
        progress.start_run("r", "s", "t")
        progress.attach(blocked)
        progress.record_error(ValueError("bad config"))
    assert "日志：未保存" in stream.getvalue()
    assert not any(item["logs"] for item in progress.diagnostics)


def test_final_inventory_updates_provisional_counts(tmp_path: Path) -> None:
    from instrument_benchmark.candidate import CandidateContract, CandidateInventory
    from instrument_benchmark.progress import ProgressReporter

    with ProgressReporter(stream=io.StringIO()) as progress:
        progress.watch_candidates(
            tmp_path,
            CandidateContract("task_environment", ("step/a",)),
            groups=("step",),
        )
        progress.stop_watching()
        assert progress.candidate_status["present"] == 0
        progress.candidates_checked(CandidateInventory(tmp_path, ("step/a",), (), ()))
        assert progress.candidate_status["present"] == 1
        assert progress.candidate_status["groups"]["step"] == [1, 1]
        assert progress.candidate_status["final"] is True


def test_failed_stage_does_not_print_a_success_marker() -> None:
    from instrument_benchmark.progress import ProgressReporter

    stream = io.StringIO()
    with ProgressReporter(stream=stream) as progress:
        with progress.stage("agent"):
            progress.record_error(RuntimeError("agent exit_code=1"))
    assert "✓ ④ Agent" not in stream.getvalue()
    assert "! ④ Agent" in stream.getvalue()


def test_fast_stage_completion_updates_tty_without_waiting_for_heartbeat() -> None:
    from instrument_benchmark.progress import ProgressReporter

    with ProgressReporter(stream=TtyStream(), refresh_interval=30) as progress:
        progress.start_run("r", "s", "t")
        with progress.stage("validate"):
            pass
        assert progress.display.run.n == 1


def test_error_log_paths_cannot_inject_terminal_controls(tmp_path: Path) -> None:
    from instrument_benchmark.progress import ProgressReporter

    log = tmp_path / "agent\x1b[2J\nforged-line.log"
    log.write_text("failure")
    stream = io.StringIO()
    with ProgressReporter(stream=stream) as progress:
        diagnostic = progress.record_error(RuntimeError("failed"), logs=[log])

    output = stream.getvalue()
    assert "\x1b" not in output
    assert "\nforged-line" not in output
    assert r"\nforged-line.log" in output
    assert diagnostic["logs"] == [str(log.resolve())]
