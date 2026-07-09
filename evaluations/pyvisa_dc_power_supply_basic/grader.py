"""Grader for the PyVISA DC power supply access instance.

Usage:
    python grader.py path/to/solution.py
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import tempfile
from pathlib import Path
from types import ModuleType

import fake_pyvisa


def load_candidate(path: Path) -> ModuleType:
    sys.modules["pyvisa"] = fake_pyvisa
    spec = importlib.util.spec_from_file_location("candidate_solution", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load candidate from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def grade(candidate_path: Path) -> dict:
    module = load_candidate(candidate_path)
    if not hasattr(module, "run_experiment"):
        raise RuntimeError("Candidate solution must expose run_experiment(output_path=...)")

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "result.json"
        result = module.run_experiment(output_path)
        if output_path.exists():
            result_from_file = json.loads(output_path.read_text(encoding="utf-8"))
        else:
            result_from_file = result

    trace = []
    resource = None
    for obj in fake_pyvisa.RESOURCE_MANAGERS:
        trace.extend(obj.trace)
        if obj.resource is not None:
            resource = obj.resource

    scores = {
        "connection": 0.0,
        "configuration": 0.0,
        "protocol_mapping": 0.0,
        "state_transition": 0.0,
        "experiment_result": 0.0,
        "cleanup": 0.0,
    }
    feedback: list[str] = []

    if any(event.kind == "open_resource" and event.payload.get("resource_name") == fake_pyvisa.RESOURCE_NAME for event in trace):
        scores["connection"] = 1.0
    else:
        feedback.append("Did not open the expected PyVISA resource.")

    if resource is not None:
        config_score = 0
        config_score += resource.timeout == 5000
        config_score += resource.read_termination == "\n"
        config_score += resource.write_termination == "\n"
        scores["configuration"] = config_score / 3
        if scores["configuration"] < 1:
            feedback.append("Missing or incorrect timeout/read_termination/write_termination.")
    else:
        feedback.append("No fake resource was created.")

    semantic = [event.payload for event in trace if event.kind == "semantic"]
    required = [
        {"action": "identify"},
        {"action": "set_voltage", "channel": 1, "value": 3.3, "unit": "V"},
        {"action": "set_current_limit", "channel": 1, "value": 0.5, "unit": "A"},
        {"action": "enable_output", "channel": 1, "value": True},
        {"action": "measure_voltage", "channel": 1},
    ]
    matched = sum(_contains_semantic(semantic, item) for item in required)
    scores["protocol_mapping"] = matched / len(required)
    if scores["protocol_mapping"] < 1:
        feedback.append("The semantic command trace does not match all required instrument actions.")

    action_order = [event.get("action") for event in semantic]
    if _is_ordered(action_order, ["set_voltage", "set_current_limit", "enable_output", "measure_voltage"]):
        scores["state_transition"] = 1.0
    else:
        feedback.append("Command order does not prove a valid state transition before measurement.")

    scores["experiment_result"] = _grade_result(result_from_file, feedback)

    closed_resource = any(event.kind == "close_resource" for event in trace)
    closed_rm = any(event.kind == "close_resource_manager" for event in trace)
    scores["cleanup"] = (int(closed_resource) + int(closed_rm)) / 2
    if scores["cleanup"] < 1:
        feedback.append("Resource and/or ResourceManager was not closed.")

    total = sum(scores.values()) / len(scores)
    return {
        "scores": scores,
        "total": round(total, 4),
        "feedback": feedback,
        "trace": [{"kind": event.kind, "payload": event.payload} for event in trace],
    }


def _contains_semantic(events: list[dict], expected: dict) -> bool:
    for event in events:
        if event.get("action") != expected.get("action"):
            continue
        ok = True
        for key, value in expected.items():
            if key == "value" and isinstance(value, float):
                ok = ok and math.isclose(float(event.get(key)), value, rel_tol=0, abs_tol=1e-6)
            else:
                ok = ok and event.get(key) == value
        if ok:
            return True
    return False


def _is_ordered(actions: list[str | None], expected_order: list[str]) -> bool:
    pos = -1
    for expected in expected_order:
        try:
            pos = actions.index(expected, pos + 1)
        except ValueError:
            return False
    return True


def _grade_result(result: dict, feedback: list[str]) -> float:
    checks = [
        result.get("instrument") == "MockDP100",
        result.get("channel") == 1,
        math.isclose(float(result.get("target_voltage_v", float("nan"))), 3.3, abs_tol=1e-6),
        math.isclose(float(result.get("current_limit_a", float("nan"))), 0.5, abs_tol=1e-6),
        3.25 <= float(result.get("measured_voltage_v", float("nan"))) <= 3.35,
        result.get("output_enabled") is True,
    ]
    score = sum(checks) / len(checks)
    if score < 1:
        feedback.append("Experiment result is missing required values or contains incorrect output.")
    return score


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python grader.py path/to/solution.py")
    report = grade(Path(sys.argv[1]).resolve())
    print(json.dumps(report, indent=2))
