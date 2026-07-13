"""Negative fixture: hard-coded observation with no simulator interaction."""

from __future__ import annotations

import json
from pathlib import Path


def run_experiment(output_path: str) -> dict:
    result = {
        "instrument": "MockDP100",
        "channel": 1,
        "target_voltage_v": 3.3,
        "current_limit_a": 0.5,
        "measured_voltage_v": 3.298,
        "output_enabled": True,
    }
    Path(output_path).write_text(json.dumps(result), encoding="utf-8")
    return result
