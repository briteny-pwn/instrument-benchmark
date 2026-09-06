from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

import instrument_benchmark.streaming_process as streaming_process_module
from instrument_benchmark.streaming_process import stream_process


def python_child(source: str) -> list[str]:
    return [sys.executable, "-c", source]


def test_callbacks_are_live_sanitized_and_run_on_calling_thread(tmp_path: Path) -> None:
    callback_times: list[float] = []
    callback_threads: list[int] = []
    started = time.monotonic()

    result = stream_process(
        python_child("import time; print('token=secret', flush=True); time.sleep(.35)"),
        stdout_path=tmp_path / "logs" / "out.log",
        stderr_path=tmp_path / "logs" / "err.log",
        on_stdout_line=lambda line: (
            callback_times.append(time.monotonic()),
            callback_threads.append(threading.get_ident()),
        ),
        sanitize=lambda text: text.replace("secret", "[redacted]"),
    )

    assert result.duration_seconds - (callback_times[0] - started) >= 0.25
    assert callback_threads == [threading.get_ident()]
    assert result.stdout == "token=[redacted]\n"
    assert (tmp_path / "logs" / "out.log").read_text() == "token=[redacted]\n"


def test_drains_both_streams_while_writing_large_stdin_and_bounds_tails(
    tmp_path: Path,
) -> None:
    size = 200_000
    source = (
        "import sys\n"
        "for _ in range(2000):\n"
        " sys.stdout.write('o' * 100 + '\\n'); sys.stderr.write('e' * 100 + '\\n')\n"
        "sys.stdout.flush(); sys.stderr.flush()\n"
        "data=sys.stdin.buffer.read()\n"
        "print('stdin=' + str(len(data)), file=sys.stderr, flush=True)\n"
    )
    result = stream_process(
        python_child(source),
        stdout_path=tmp_path / "out.log",
        stderr_path=tmp_path / "err.log",
        input_text="x" * size,
        timeout=5,
    )

    assert result.returncode == 0
    assert not result.timed_out
    assert len(result.stdout.encode()) <= 64 * 1024
    assert len(result.stderr.encode()) <= 64 * 1024
    assert f"stdin={size}" in result.stderr
    assert (tmp_path / "out.log").stat().st_size > 64 * 1024
    assert (tmp_path / "err.log").stat().st_size > 64 * 1024


def test_timeout_preserves_partial_logs_and_reaps_process_group(tmp_path: Path) -> None:
    result = stream_process(
        python_child("import time; print('partial', flush=True); time.sleep(30)"),
        stdout_path=tmp_path / "out.log",
        stderr_path=tmp_path / "err.log",
        timeout=0.15,
    )

    assert result.timed_out
    assert result.returncode != 0
    assert result.stdout == "partial\n"
    assert result.duration_seconds < 2


def test_nonzero_exit_is_a_normal_result(tmp_path: Path) -> None:
    result = stream_process(
        python_child("import sys; print('bad', file=sys.stderr); raise SystemExit(7)"),
        stdout_path=tmp_path / "out.log",
        stderr_path=tmp_path / "err.log",
    )
    assert result.returncode == 7
    assert result.stderr == "bad\n"


def test_launch_error_propagates(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        stream_process(
            [str(tmp_path / "does-not-exist")],
            stdout_path=tmp_path / "out.log",
            stderr_path=tmp_path / "err.log",
        )


def test_split_utf8_and_secret_are_sanitized_as_one_record(tmp_path: Path) -> None:
    source = (
        "import os, time\n"
        "for part in [b'caf', b'\\xc3', b'\\xa9 SECRET', b'_VALUE\\n']:\n"
        " os.write(1, part); time.sleep(.02)\n"
    )
    seen: list[str] = []
    result = stream_process(
        python_child(source),
        stdout_path=tmp_path / "out.log",
        stderr_path=tmp_path / "err.log",
        on_stdout_line=seen.append,
        sanitize=lambda text: text.replace("SECRET_VALUE", "***"),
    )
    assert result.stdout == "café ***\n"
    assert seen == ["café ***\n"]
    assert "SECRET" not in (tmp_path / "out.log").read_text()


def test_large_non_newline_record_spills_safely_and_returns_bounded_tail(
    tmp_path: Path,
) -> None:
    result = stream_process(
        python_child("import sys; sys.stdout.write('z' * 200000); sys.stdout.flush()"),
        stdout_path=tmp_path / "out.log",
        stderr_path=tmp_path / "err.log",
    )
    assert len(result.stdout.encode()) == 64 * 1024
    assert set(result.stdout) == {"z"}
    assert (tmp_path / "out.log").stat().st_size == 200000


def test_oversized_logical_record_is_replaced_without_leaking_raw_content(
    tmp_path: Path,
) -> None:
    source = "import sys; sys.stdout.write('SECRET' + 'x' * 1100000 + '\\nnext\\n')"
    sanitized_records: list[str] = []

    def sanitize(text: str) -> str:
        sanitized_records.append(text)
        return text.replace("SECRET", "***")

    result = stream_process(
        python_child(source),
        stdout_path=tmp_path / "out.log",
        stderr_path=tmp_path / "err.log",
        sanitize=sanitize,
    )
    expected = "[oversized output record omitted]\nnext\n"
    assert result.stdout == expected
    assert (tmp_path / "out.log").read_text() == expected
    assert "SECRET" not in result.stdout
    assert sanitized_records == ["next\n"]


@pytest.mark.parametrize("raised", [RuntimeError("stop"), KeyboardInterrupt()])
def test_callback_exception_propagates_after_group_cleanup(
    tmp_path: Path, raised: BaseException
) -> None:
    def fail(_: str) -> None:
        raise raised

    started = time.monotonic()
    with pytest.raises(type(raised)):
        stream_process(
            python_child("import time; print('ready', flush=True); time.sleep(30)"),
            stdout_path=tmp_path / "out.log",
            stderr_path=tmp_path / "err.log",
            on_stdout_line=fail,
        )
    assert time.monotonic() - started < 2


def test_callback_failure_closes_all_retained_popen_pipes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launched = []
    real_popen = streaming_process_module.subprocess.Popen

    def retaining_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        launched.append(process)
        return process

    monkeypatch.setattr(streaming_process_module.subprocess, "Popen", retaining_popen)

    with pytest.raises(RuntimeError, match="callback failed"):
        stream_process(
            python_child("import time; print('ready', flush=True); time.sleep(30)"),
            stdout_path=tmp_path / "out.log",
            stderr_path=tmp_path / "err.log",
            input_text="unused",
            on_stdout_line=lambda _: (_ for _ in ()).throw(
                RuntimeError("callback failed")
            ),
        )

    process = launched[0]
    assert process.stdin is not None and process.stdin.closed
    assert process.stdout is not None and process.stdout.closed
    assert process.stderr is not None and process.stderr.closed


def test_timeout_still_applies_after_child_closes_output_pipes(tmp_path: Path) -> None:
    source = "import os, time\nos.close(1); os.close(2)\ntime.sleep(30)\n"
    started = time.monotonic()
    result = stream_process(
        python_child(source),
        stdout_path=tmp_path / "out.log",
        stderr_path=tmp_path / "err.log",
        timeout=0.15,
    )
    assert result.timed_out
    assert result.returncode != 0
    assert time.monotonic() - started < 2


def test_stop_group_bounds_every_reap_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    class UnreapableProcess:
        pid = 99999999

        def __init__(self) -> None:
            self.wait_timeouts: list[float | None] = []

        def poll(self):
            return None

        def wait(self, timeout=None):
            self.wait_timeouts.append(timeout)
            raise streaming_process_module.subprocess.TimeoutExpired(["child"], timeout)

    process = UnreapableProcess()
    monkeypatch.setattr(streaming_process_module, "_signal_group", lambda *_: None)
    monkeypatch.setattr(streaming_process_module, "_TERM_GRACE_SECONDS", 0.01)

    with pytest.raises(streaming_process_module.subprocess.TimeoutExpired):
        streaming_process_module._stop_group(process)
    assert process.wait_timeouts == [0.01, 0.01]


def test_cleanup_timeout_does_not_mask_callback_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_stop_group = streaming_process_module._stop_group

    def stop_then_report_failure(process) -> None:
        real_stop_group(process)
        raise streaming_process_module.subprocess.TimeoutExpired(["child"], 0.5)

    monkeypatch.setattr(
        streaming_process_module, "_stop_group", stop_then_report_failure
    )

    with pytest.raises(RuntimeError, match="callback failed") as caught:
        stream_process(
            python_child("import time; print('ready', flush=True); time.sleep(30)"),
            stdout_path=tmp_path / "out.log",
            stderr_path=tmp_path / "err.log",
            on_stdout_line=lambda _: (_ for _ in ()).throw(
                RuntimeError("callback failed")
            ),
        )
    assert any("cleanup" in note.lower() for note in caught.value.__notes__)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX fork")
def test_does_not_hang_when_descendant_keeps_pipe_descriptors_open(
    tmp_path: Path,
) -> None:
    source = (
        "import os, time\n"
        "if os.fork() == 0:\n"
        " time.sleep(30); os._exit(0)\n"
        "print('parent done', flush=True)\n"
    )
    started = time.monotonic()
    result = stream_process(
        python_child(source),
        stdout_path=tmp_path / "out.log",
        stderr_path=tmp_path / "err.log",
    )
    assert result.returncode == 0
    assert result.stdout == "parent done\n"
    assert time.monotonic() - started < 2


def test_poll_failure_stops_quiet_child_and_preserves_original_error(tmp_path):
    import time
    import sys
    from instrument_benchmark.streaming_process import stream_process

    started = time.monotonic()
    calls = []
    error = RuntimeError("step_1 export denied")

    def check():
        calls.append(time.monotonic())
        if len(calls) >= 5:
            raise error

    with pytest.raises(RuntimeError, match="export denied") as caught:
        stream_process(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout_path=tmp_path / "stdout",
            stderr_path=tmp_path / "stderr",
            on_poll=check,
        )
    assert caught.value is error
    assert time.monotonic() - started < 3


def test_prelaunch_health_failure_does_not_start_child(tmp_path):
    import sys
    from instrument_benchmark.streaming_process import stream_process

    marker = tmp_path / "launched"

    def check():
        raise RuntimeError("environment already failed")

    with pytest.raises(RuntimeError, match="already failed"):
        stream_process(
            [
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).touch()",
            ],
            stdout_path=tmp_path / "stdout",
            stderr_path=tmp_path / "stderr",
            on_poll=check,
        )
    assert not marker.exists()
