from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def result(status="completed", **extra):
    return {"run_id": "r", "status": status, "diagnostics": [], **extra}


def event(sequence=1, kind="ready", **extra):
    return {
        "run_id": "r",
        "sequence": sequence,
        "kind": kind,
        "step": "startup",
        "error_type": "",
        "error": "",
        "logs": [],
        **extra,
    }


def reader(root):
    from instrument_benchmark.task_environment_status import EnvironmentStatusReader

    return EnvironmentStatusReader(root, "r")


def test_result_keeps_original_error_and_host_log_path(tmp_path):
    (tmp_path / "error.log").write_text("traceback")
    diagnostic = {
        "step": "step_1",
        "error_type": "PermissionError",
        "error": "export denied",
        "logs": ["error.log"],
    }
    (tmp_path / "environment-result.json").write_text(
        json.dumps(result("infrastructure_failure", diagnostics=[diagnostic]))
    )
    value = reader(tmp_path).read_result()
    assert value.status == "infrastructure_failure"
    assert value.diagnostics[0].step == "step_1"
    assert value.diagnostics[0].error_type == "PermissionError"
    assert value.diagnostics[0].logs == (tmp_path / "error.log",)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "{",
        json.dumps(result("unknown")),
        json.dumps(result(run_id="other")),
        json.dumps({**result(), "version": 1}),
        json.dumps(
            result(
                diagnostics=[
                    {
                        "step": "s",
                        "error_type": "Error",
                        "error": "x",
                        "logs": ["../outside"],
                    }
                ]
            )
        ),
    ],
)
def test_missing_or_invalid_final_result_is_not_success(tmp_path, payload):
    from instrument_benchmark.task_environment_status import TaskEnvironmentStatusError

    if payload is not None:
        (tmp_path / "environment-result.json").write_text(payload)
    with pytest.raises(TaskEnvironmentStatusError):
        reader(tmp_path).read_result()


def test_partial_event_waits_for_newline_and_is_delivered_once(tmp_path):
    path = tmp_path / "environment-events.jsonl"
    encoded = json.dumps(event())
    status = reader(tmp_path)
    assert status.poll() == ()
    path.write_text(encoded[:20])
    assert status.poll() == ()
    with path.open("a") as stream:
        stream.write(encoded[20:] + "\n")
    assert status.poll()[0].kind == "ready"
    assert status.poll() == ()
    with path.open("a") as stream:
        stream.write(
            json.dumps(
                event(
                    2,
                    "candidate_error",
                    step="step_1",
                    error_type="RejectedOperation",
                    error="bad argument",
                )
            )
            + "\n"
        )
    assert status.poll()[0].kind == "candidate_error"


@pytest.mark.parametrize(
    "payload",
    [
        "x" * 65537,
        json.dumps(event(sequence=2)) + "\n",
        json.dumps(event(sequence=True)) + "\n",
        '{"run_id":NaN}\n',
    ],
    ids=["oversize", "sequence-gap", "bool-sequence", "non-finite"],
)
def test_invalid_event_stream_is_rejected(tmp_path, payload):
    from instrument_benchmark.task_environment_status import TaskEnvironmentStatusError

    (tmp_path / "environment-events.jsonl").write_text(payload)
    with pytest.raises(TaskEnvironmentStatusError):
        reader(tmp_path).poll()


def test_trailing_partial_event_rejected_at_finalization(tmp_path):
    from instrument_benchmark.task_environment_status import TaskEnvironmentStatusError

    (tmp_path / "environment-events.jsonl").write_text('{"run_id":')
    (tmp_path / "environment-result.json").write_text(json.dumps(result()))
    with pytest.raises(TaskEnvironmentStatusError):
        reader(tmp_path).read_result()


def test_fatal_event_cannot_be_overridden_by_success(tmp_path):
    from instrument_benchmark.task_environment_status import TaskEnvironmentStatusError

    (tmp_path / "environment-events.jsonl").write_text(
        json.dumps(
            event(
                kind="environment_error", error_type="PermissionError", error="denied"
            )
        )
        + "\n"
    )
    (tmp_path / "environment-result.json").write_text(json.dumps(result()))
    with pytest.raises(TaskEnvironmentStatusError):
        reader(tmp_path).read_result()


def test_symlink_result_is_rejected(tmp_path):
    from instrument_benchmark.task_environment_status import TaskEnvironmentStatusError

    target = tmp_path / "other.json"
    target.write_text(json.dumps(result()))
    (tmp_path / "environment-result.json").symlink_to(target)
    with pytest.raises(TaskEnvironmentStatusError):
        reader(tmp_path).read_result()


def test_reader_consumes_actual_tasks_publisher(tmp_path):
    tasks = Path(__file__).resolve().parents[2] / "instrument-benchmark-instances"
    code = (
        "from pathlib import Path\n"
        "from sources.openfibsem.task_environment.runtime_status import RuntimeStatus\n"
        f"status = RuntimeStatus(Path({str(tmp_path)!r}), 'r')\n"
        "status.emit('ready', 'startup')\n"
        "status.emit('environment_error', 'step_1', PermissionError('denied'))\n"
        "status.finish('completed')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=tasks, text=True, capture_output=True
    )
    assert completed.returncode == 0, completed.stderr
    value = reader(tmp_path)
    assert [item.kind for item in value.poll()] == ["ready", "environment_error"]
    assert value.read_result().status == "infrastructure_failure"
