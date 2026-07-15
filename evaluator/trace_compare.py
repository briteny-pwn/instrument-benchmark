"""Behavioral trace comparison that permits implementation-level differences."""

from __future__ import annotations

from typing import Any


def compare_traces(actual: list[dict[str, Any]], expected: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Compare ordered semantic checkpoints, ignoring timestamps and extra events."""
    errors: list[str] = []
    cursor = 0
    for wanted in expected:
        found = False
        while cursor < len(actual):
            event = actual[cursor]
            cursor += 1
            if all(event.get(key) == value for key, value in wanted.items()):
                found = True
                break
        if not found: errors.append(f"missing ordered checkpoint: {wanted}")
    return not errors, errors
