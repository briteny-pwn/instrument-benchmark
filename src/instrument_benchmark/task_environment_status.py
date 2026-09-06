"""Source-independent task-environment evidence consumed by Instrument."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

STATUSES = frozenset(
    {
        "completed",
        "candidate_incomplete",
        "candidate_failure",
        "infrastructure_failure",
        "interrupted",
    }
)
KINDS = frozenset({"ready", "candidate_error", "environment_error"})
MAX_EVENT_BYTES = 65536
MAX_RESULT_BYTES = 1024 * 1024


class TaskEnvironmentStatusError(RuntimeError):
    """The environment did not provide a valid, complete execution status."""


@dataclass(frozen=True)
class EnvironmentDiagnostic:
    step: str
    error_type: str
    error: str
    logs: tuple[Path, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "step": self.step,
            "error_type": self.error_type,
            "error": self.error,
            "logs": [str(path) for path in self.logs],
        }


@dataclass(frozen=True)
class EnvironmentEvent:
    sequence: int
    kind: str
    diagnostic: EnvironmentDiagnostic


@dataclass(frozen=True)
class TaskEnvironmentResult:
    status: str
    diagnostics: tuple[EnvironmentDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


def _regular_file(path: Path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise TaskEnvironmentStatusError(f"not a regular status file: {path}")
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def _json(payload: bytes) -> dict:
    def reject_constant(value):
        raise ValueError(f"invalid JSON constant: {value}")

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload, parse_constant=reject_constant, object_pairs_hook=unique_pairs
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise TaskEnvironmentStatusError("invalid environment status JSON") from exc
    if not isinstance(value, dict):
        raise TaskEnvironmentStatusError("environment status must be an object")
    return value


class EnvironmentStatusReader:
    def __init__(self, evidence_root: Path, run_id: str):
        self.root = evidence_root.resolve()
        self.run_id = run_id
        self._offset = 0
        self._pending = b""
        self._sequence = 0
        self._identity: tuple[int, int] | None = None
        self.fatal: EnvironmentDiagnostic | None = None

    def _diagnostic(self, value: object) -> EnvironmentDiagnostic:
        if not isinstance(value, dict) or set(value) != {
            "step",
            "error_type",
            "error",
            "logs",
        }:
            raise TaskEnvironmentStatusError("invalid environment diagnostic fields")
        if any(
            not isinstance(value[name], str) or len(value[name]) > 8192
            for name in ("step", "error_type", "error")
        ):
            raise TaskEnvironmentStatusError("invalid environment diagnostic text")
        logs = value["logs"]
        if not isinstance(logs, list) or len(logs) > 32:
            raise TaskEnvironmentStatusError("invalid environment diagnostic logs")
        resolved = []
        for raw in logs:
            if (
                not isinstance(raw, str)
                or not raw
                or len(raw) > 1024
                or "\\" in raw
                or Path(raw).is_absolute()
                or any(part in {"", ".", ".."} for part in raw.split("/"))
            ):
                raise TaskEnvironmentStatusError("unsafe environment log path")
            path = self.root / raw
            if not path.resolve().is_relative_to(self.root):
                raise TaskEnvironmentStatusError(
                    "environment log escapes evidence root"
                )
            try:
                with _regular_file(path):
                    pass
            except OSError as exc:
                raise TaskEnvironmentStatusError(
                    f"cannot read environment log: {path}"
                ) from exc
            resolved.append(path)
        return EnvironmentDiagnostic(
            value["step"], value["error_type"], value["error"], tuple(resolved)
        )

    def poll(self) -> tuple[EnvironmentEvent, ...]:
        path = self.root / "environment-events.jsonl"
        try:
            with _regular_file(path) as stream:
                metadata = os.fstat(stream.fileno())
                identity = (metadata.st_dev, metadata.st_ino)
                if (
                    self._identity is not None and identity != self._identity
                ) or metadata.st_size < self._offset:
                    raise TaskEnvironmentStatusError(
                        "environment event stream replaced or truncated"
                    )
                self._identity = identity
                stream.seek(self._offset)
                payload = stream.read(MAX_RESULT_BYTES)
                self._offset += len(payload)
        except FileNotFoundError as exc:
            if self._identity is not None:
                raise TaskEnvironmentStatusError(
                    "environment event stream disappeared"
                ) from exc
            return ()
        except OSError as exc:
            raise TaskEnvironmentStatusError(
                f"cannot read environment events: {path}"
            ) from exc
        records = (self._pending + payload).split(b"\n")
        self._pending = records.pop()
        if len(self._pending) > MAX_EVENT_BYTES:
            raise TaskEnvironmentStatusError("environment event exceeds size limit")
        events = []
        for record in records:
            if len(record) > MAX_EVENT_BYTES:
                raise TaskEnvironmentStatusError("environment event exceeds size limit")
            value = _json(record)
            if (
                set(value)
                != {"run_id", "sequence", "kind", "step", "error_type", "error", "logs"}
                or value["run_id"] != self.run_id
                or type(value["sequence"]) is not int
                or value["sequence"] != self._sequence + 1
                or not isinstance(value["kind"], str)
                or value["kind"] not in KINDS
            ):
                raise TaskEnvironmentStatusError(
                    "invalid environment event identity, sequence or kind"
                )
            diagnostic = self._diagnostic(
                {key: value[key] for key in ("step", "error_type", "error", "logs")}
            )
            self._sequence = value["sequence"]
            if value["kind"] == "environment_error" and self.fatal is None:
                self.fatal = diagnostic
            events.append(EnvironmentEvent(self._sequence, value["kind"], diagnostic))
        return tuple(events)

    def read_result(self) -> TaskEnvironmentResult:
        while True:
            previous = self._offset
            self.poll()
            if self._offset == previous:
                break
        if self._pending:
            raise TaskEnvironmentStatusError("incomplete final environment event")
        path = self.root / "environment-result.json"
        try:
            with _regular_file(path) as stream:
                payload = stream.read(MAX_RESULT_BYTES + 1)
        except OSError as exc:
            raise TaskEnvironmentStatusError(
                f"cannot read final environment result: {path}"
            ) from exc
        if len(payload) > MAX_RESULT_BYTES:
            raise TaskEnvironmentStatusError("environment result exceeds size limit")
        value = _json(payload)
        if (
            set(value) != {"run_id", "status", "diagnostics"}
            or value["run_id"] != self.run_id
            or not isinstance(value["status"], str)
            or value["status"] not in STATUSES
            or not isinstance(value["diagnostics"], list)
        ):
            raise TaskEnvironmentStatusError("invalid final environment result fields")
        if self.fatal and value["status"] != "infrastructure_failure":
            raise TaskEnvironmentStatusError(
                "fatal environment event contradicts final result"
            )
        return TaskEnvironmentResult(
            value["status"],
            tuple(self._diagnostic(item) for item in value["diagnostics"]),
        )
