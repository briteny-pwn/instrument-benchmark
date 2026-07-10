"""Grader for the PyVISA DMM ASCII average instance.

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

import trace_pyvisa


EXPECTED_SAMPLES = [1.001, 1.003, 0.999, 1.002, 1.0]
EXPECTED_AVERAGE = sum(EXPECTED_SAMPLES) / len(EXPECTED_SAMPLES)


def load_candidate(path: Path) -> ModuleType:
    trace_pyvisa.reset_trace()
    trace_pyvisa.install()
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

    feedback: list[str] = []
    pyvisa_sim_execution = 1.0
    result_from_file: dict = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "result.json"
        try:
            result = module.run_experiment(output_path)
            if output_path.exists():
                result_from_file = json.loads(output_path.read_text(encoding="utf-8"))
            else:
                result_from_file = result
        except Exception as exc:
            pyvisa_sim_execution = 0.0
            feedback.append(f"Candidate failed while running against pyvisa-sim: {exc}")

    trace = trace_pyvisa.TRACE
    scores = {
        "pyvisa_sim_execution": pyvisa_sim_execution,
        "connection": 0.0,
        "configuration": 0.0,
        "protocol_mapping": 0.0,
        "state_transition": 0.0,
        "experiment_result": 0.0,
        "cleanup": 0.0,
    }

    if any(event.kind == "open_resource" and event.payload.get("resource_name") == trace_pyvisa.RESOURCE_NAME for event in trace):
        scores["connection"] = 1.0
    else:
        feedback.append("Did not open the expected PyVISA resource.")

    attributes = {
        event.payload["name"]: event.payload["value"]
        for event in trace
        if event.kind == "set_attribute"
    }
    config_score = 0
    config_score += attributes.get("timeout") == 10000
    config_score += attributes.get("read_termination") == "\n"
    config_score += attributes.get("write_termination") == "\n"
    scores["configuration"] = config_score / 3
    if scores["configuration"] < 1:
        feedback.append("Missing or incorrect timeout/read_termination/write_termination.")

    semantic = [event.payload for event in trace if event.kind == "semantic"]
    required = [
        {"action": "identify"},
        {"action": "reset"},
        {"action": "configure_dc_voltage"},
        {"action": "set_voltage_range", "range_v": 10.0},
        {"action": "set_voltage_resolution", "resolution_v": 0.001},
        {"action": "set_sample_count", "count": 5},
        {"action": "initiate"},
        {"action": "read_trace_data"},
        {"action": "clear_trace"},
    ]
    matched = sum(_contains_semantic(semantic, item) for item in required)
    scores["protocol_mapping"] = matched / len(required)
    if scores["protocol_mapping"] < 1:
        feedback.append("The semantic command trace does not match all required DMM actions.")

    action_order = [event.get("action") for event in semantic]
    expected_order = [
        "reset",
        "configure_dc_voltage",
        "set_voltage_range",
        "set_voltage_resolution",
        "set_sample_count",
        "initiate",
        "read_trace_data",
        "clear_trace",
    ]
    if _is_ordered(action_order, expected_order):
        scores["state_transition"] = 1.0
    else:
        feedback.append("Command order does not prove a valid DMM acquisition flow.")

    if result_from_file:
        scores["experiment_result"] = _grade_result(result_from_file, feedback)
    else:
        feedback.append("No experiment result was produced.")

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
            if isinstance(value, float):
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
    samples = result.get("samples_v", [])
    checks = [
        result.get("instrument") == "MockDMM2000",
        result.get("measurement") == "dc_voltage",
        result.get("sample_count") == 5,
        _float_list_close(samples, EXPECTED_SAMPLES),
        math.isclose(float(result.get("average_voltage_v", float("nan"))), EXPECTED_AVERAGE, abs_tol=1e-9),
        result.get("unit") == "V",
    ]
    score = sum(checks) / len(checks)
    if score < 1:
        feedback.append("Experiment result is missing required values or contains incorrect output.")
    return score


def _float_list_close(values: object, expected: list[float]) -> bool:
    if not isinstance(values, list) or len(values) != len(expected):
        return False
    return all(math.isclose(float(v), e, abs_tol=1e-9) for v, e in zip(values, expected))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python grader.py path/to/solution.py")
    report = grade(Path(sys.argv[1]).resolve())
    print(json.dumps(report, indent=2))
