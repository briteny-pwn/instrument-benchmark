"""Run a subprocess while safely streaming its output to durable log files."""

from __future__ import annotations

import codecs
import os
import selectors
import signal
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

_TAIL_BYTES = 64 * 1024
_MAX_RECORD_CHARACTERS = 1024 * 1024
_OVERSIZED_RECORD = "[oversized output record omitted]\n"
_TERM_GRACE_SECONDS = 0.5
_ORPHANED_PIPE_GRACE_SECONDS = 0.2


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_seconds: float


class _StreamSink:
    def __init__(
        self,
        log_file: BinaryIO,
        callback: Callable[[str], None] | None,
        sanitize: Callable[[str], str],
    ) -> None:
        self._log_file = log_file
        self._callback = callback
        self._sanitize = sanitize
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._record_parts: list[str] = []
        self._record_characters = 0
        self._record_oversized = False
        self._tail = bytearray()

    def feed(self, data: bytes) -> None:
        self._consume_text(self._decoder.decode(data))

    def finish(self) -> None:
        self._consume_text(self._decoder.decode(b"", final=True))
        if self._record_oversized:
            self._emit_oversized_record()
        elif self._record_characters:
            self._emit_record()

    def close(self) -> None:
        self._record_parts.clear()

    def tail(self) -> str:
        # The byte cap can bisect the first UTF-8 character. Dropping only that
        # partial prefix keeps the returned value valid and within the byte cap.
        return bytes(self._tail).decode("utf-8", errors="ignore")

    def _consume_text(self, text: str) -> None:
        while text:
            newline = text.find("\n")
            if newline < 0:
                self._append_record_text(text)
                return
            self._append_record_text(text[: newline + 1])
            if self._record_oversized:
                self._emit_oversized_record()
            else:
                self._emit_record()
            text = text[newline + 1 :]

    def _append_record_text(self, text: str) -> None:
        if self._record_oversized:
            return
        if self._record_characters + len(text) > _MAX_RECORD_CHARACTERS:
            # Never expose a raw prefix or suffix: either could contain part of a
            # secret that an arbitrary complete-record sanitizer would remove.
            self._record_parts.clear()
            self._record_characters = 0
            self._record_oversized = True
            return
        self._record_parts.append(text)
        self._record_characters += len(text)

    def _emit_record(self) -> None:
        record = "".join(self._record_parts)
        self._reset_record()
        sanitized = self._sanitize(record)
        self._emit_sanitized(sanitized)

    def _emit_oversized_record(self) -> None:
        self._reset_record()
        self._emit_sanitized(_OVERSIZED_RECORD)

    def _reset_record(self) -> None:
        self._record_parts.clear()
        self._record_characters = 0
        self._record_oversized = False

    def _emit_sanitized(self, sanitized: str) -> None:
        encoded = sanitized.encode("utf-8")
        self._log_file.write(encoded)
        self._log_file.flush()
        self._tail.extend(encoded)
        if len(self._tail) > _TAIL_BYTES:
            del self._tail[: len(self._tail) - _TAIL_BYTES]
        if self._callback is not None:
            self._callback(sanitized)


def _signal_group(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass


def _stop_group(process: subprocess.Popen[bytes]) -> None:
    _signal_group(process, signal.SIGTERM)
    deadline = time.monotonic() + _TERM_GRACE_SECONDS
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    # Send SIGKILL even after the group leader exits: descendants may remain.
    _signal_group(process, signal.SIGKILL)
    try:
        process.wait(timeout=_TERM_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        _signal_group(process, signal.SIGKILL)
        # Do not claim cleanup succeeded if the operating system still cannot
        # confirm reaping after SIGKILL. Propagate the bounded wait failure.
        process.wait(timeout=_TERM_GRACE_SECONDS)


def stream_process(
    command: Sequence[str],
    *,
    stdout_path: Path,
    stderr_path: Path,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
    timeout: float | None = None,
    on_stdout_line: Callable[[str], None] | None = None,
    on_stderr_line: Callable[[str], None] | None = None,
    sanitize: Callable[[str], str] | None = None,
    on_poll: Callable[[], None] | None = None,
) -> ProcessResult:
    """Run *command*, streaming sanitized logical records to files and callbacks.

    Records over one MiB of decoded text are discarded through their next newline
    and replaced with a neutral omission marker; no raw fragment is exposed.
    """
    started = time.monotonic()
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    sanitizer = sanitize or (lambda text: text)
    process: subprocess.Popen[bytes] | None = None
    selector = selectors.DefaultSelector()
    stdout_sink: _StreamSink | None = None
    stderr_sink: _StreamSink | None = None
    timed_out = False

    with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
        try:
            if on_poll is not None:
                on_poll()
            process = subprocess.Popen(
                list(command),
                cwd=cwd,
                env=None if env is None else dict(env),
                stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            assert process.stdout is not None and process.stderr is not None
            stdout_sink = _StreamSink(stdout_file, on_stdout_line, sanitizer)
            stderr_sink = _StreamSink(stderr_file, on_stderr_line, sanitizer)
            for pipe, sink in (
                (process.stdout, stdout_sink),
                (process.stderr, stderr_sink),
            ):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, ("read", sink))

            pending_input = memoryview((input_text or "").encode("utf-8"))
            input_offset = 0
            if process.stdin is not None:
                os.set_blocking(process.stdin.fileno(), False)
                if pending_input:
                    selector.register(
                        process.stdin, selectors.EVENT_WRITE, ("write", None)
                    )
                else:
                    process.stdin.close()

            exit_seen_at: float | None = None
            while selector.get_map() or process.poll() is None:
                if on_poll is not None:
                    on_poll()
                now = time.monotonic()
                if timeout is not None and now - started >= timeout and not timed_out:
                    timed_out = True
                    _stop_group(process)

                if process.poll() is not None:
                    exit_seen_at = exit_seen_at or now
                    if now - exit_seen_at >= _ORPHANED_PIPE_GRACE_SECONDS:
                        # A descendant inherited our descriptors. It belongs to the
                        # isolated process group, so close it rather than hanging.
                        _signal_group(process, signal.SIGKILL)
                        break

                wait = 0.05
                if timeout is not None and not timed_out:
                    wait = max(0.0, min(wait, timeout - (now - started)))
                for key, _ in selector.select(wait):
                    kind, sink = key.data
                    pipe = key.fileobj
                    if kind == "write":
                        try:
                            written = os.write(
                                pipe.fileno(),
                                pending_input[input_offset : input_offset + 65536],
                            )
                            input_offset += written
                        except BrokenPipeError:
                            input_offset = len(pending_input)
                        if input_offset >= len(pending_input):
                            selector.unregister(pipe)
                            pipe.close()
                    else:
                        try:
                            chunk = os.read(pipe.fileno(), 65536)
                        except BlockingIOError:
                            continue
                        if chunk:
                            sink.feed(chunk)
                        else:
                            selector.unregister(pipe)
                            pipe.close()
                            sink.finish()

            # Finish streams whose EOF was suppressed by inherited descriptors.
            for pipe, sink in (
                (process.stdout, stdout_sink),
                (process.stderr, stderr_sink),
            ):
                if not pipe.closed:
                    try:
                        selector.unregister(pipe)
                    except KeyError:
                        pass
                    pipe.close()
                    sink.finish()
            if process.stdin is not None and not process.stdin.closed:
                try:
                    selector.unregister(process.stdin)
                except KeyError:
                    pass
                process.stdin.close()
            process.wait()
        except BaseException as error:
            if process is not None:
                try:
                    _stop_group(process)
                except BaseException as cleanup_error:
                    error.add_note(
                        "Subprocess cleanup also failed: "
                        f"{type(cleanup_error).__name__}: {cleanup_error}"
                    )
            raise
        finally:
            selector.close()
            if process is not None:
                for pipe in (process.stdin, process.stdout, process.stderr):
                    if pipe is not None and not pipe.closed:
                        pipe.close()
            if stdout_sink is not None:
                stdout_sink.close()
            if stderr_sink is not None:
                stderr_sink.close()

    assert process is not None and stdout_sink is not None and stderr_sink is not None
    return ProcessResult(
        returncode=process.returncode,
        stdout=stdout_sink.tail(),
        stderr=stderr_sink.tail(),
        timed_out=timed_out,
        duration_seconds=time.monotonic() - started,
    )
