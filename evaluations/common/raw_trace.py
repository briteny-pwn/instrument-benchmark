"""Trace storage for raw socket instrument simulations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TRACE: list["TraceEvent"] = []


@dataclass
class TraceEvent:
    kind: str
    payload: dict[str, Any]


def reset_trace() -> None:
    TRACE.clear()


def record(kind: str, payload: dict[str, Any] | None = None) -> None:
    TRACE.append(TraceEvent(kind, payload or {}))


def serializable_trace() -> list[dict[str, Any]]:
    return [{"kind": event.kind, "payload": _jsonable(event.payload)} for event in TRACE]


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)

