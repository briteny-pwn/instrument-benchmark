"""Grader for the PyVISA resource discovery IDN instance."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import tempfile
from pathlib import Path
from types import ModuleType

import trace_pyvisa


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
            result_from_file = json.loads(output_path.read_text(encoding="utf-8")) if output_path.exists() else result
        except Exception as exc:
            pyvisa_sim_execution = 0.0
            feedback.append(f"Candidate failed while running against pyvisa-sim: {exc}")

    trace = trace_pyvisa.TRACE
    scores = {
        "pyvisa_sim_execution": pyvisa_sim_execution,
        "resource_discovery": 0.0,
        "idn_selection": 0.0,
        "configuration": 0.0,
        "protocol_mapping": 0.0,
        "experiment_result": 0.0,
        "cleanup": 0.0,
    }

    if any(event.kind == "list_resources" for event in trace):
        scores["resource_discovery"] = 1.0
    else:
        feedback.append("Did not call ResourceManager.list_resources().")

    idn_resources = {event.payload.get("resource_name") for event in trace if event.kind == "semantic" and event.payload.get("action") == "identify"}
    opened_target = any(event.kind == "open_resource" and event.payload.get("resource_name") == trace_pyvisa.RESOURCE_NAME for event in trace)
    if opened_target and len(idn_resources) >= 2 and trace_pyvisa.RESOURCE_NAME in idn_resources:
        scores["idn_selection"] = 1.0
    elif opened_target and trace_pyvisa.RESOURCE_NAME in idn_resources:
        scores["idn_selection"] = 0.5
        feedback.append("Opened target resource, but trace does not prove discovery across multiple IDN candidates.")
    else:
        feedback.append("Did not select MockLogger300 by querying identities.")

    target_attributes = {
        event.payload["name"]: event.payload["value"]
        for event in trace
        if event.kind == "set_attribute" and event.payload.get("resource_name") == trace_pyvisa.RESOURCE_NAME
    }
    config_checks = [
        target_attributes.get("timeout") == 4000,
        target_attributes.get("read_termination") == "\n",
        target_attributes.get("write_termination") == "\n",
    ]
    scores["configuration"] = sum(config_checks) / len(config_checks)
    if scores["configuration"] < 1:
        feedback.append("Missing or incorrect target timeout/read_termination/write_termination.")

    semantic = [event.payload for event in trace if event.kind == "semantic" and event.payload.get("resource_name") == trace_pyvisa.RESOURCE_NAME]
    required = [
        {"action": "identify"},
        {"action": "reset"},
        {"action": "select_channel", "channel": "A"},
        {"action": "measure_temperature", "channel": "A"},
        {"action": "measure_humidity", "channel": "A"},
    ]
    scores["protocol_mapping"] = sum(_contains_semantic(semantic, item) for item in required) / len(required)
    if scores["protocol_mapping"] < 1:
        feedback.append("The semantic command trace does not match all required logger actions.")

    scores["experiment_result"] = _grade_result(result_from_file, feedback) if result_from_file else 0.0
    if not result_from_file:
        feedback.append("No experiment result was produced.")

    opened = [event.payload.get("resource_name") for event in trace if event.kind == "open_resource"]
    closed = [event.payload.get("resource_name") for event in trace if event.kind == "close_resource"]
    closed_all = opened and all(resource in closed for resource in opened)
    closed_rm = any(event.kind == "close_resource_manager" for event in trace)
    scores["cleanup"] = (int(bool(closed_all)) + int(closed_rm)) / 2
    if scores["cleanup"] < 1:
        feedback.append("All opened resources and the ResourceManager should be closed.")

    total = sum(scores.values()) / len(scores)
    return {"scores": scores, "total": round(total, 4), "feedback": feedback, "trace": [{"kind": e.kind, "payload": e.payload} for e in trace]}


def _contains_semantic(events: list[dict], expected: dict) -> bool:
    for event in events:
        if event.get("action") != expected.get("action"):
            continue
        if all(event.get(key) == value for key, value in expected.items()):
            return True
    return False


def _grade_result(result: dict, feedback: list[str]) -> float:
    checks = [
        result.get("instrument") == "MockLogger300",
        result.get("selected_resource") == trace_pyvisa.RESOURCE_NAME,
        result.get("channel") == "A",
        math.isclose(float(result.get("temperature_c", float("nan"))), 23.45, abs_tol=1e-9),
        math.isclose(float(result.get("relative_humidity_percent", float("nan"))), 45.6, abs_tol=1e-9),
    ]
    score = sum(checks) / len(checks)
    if score < 1:
        feedback.append("Experiment result is missing required values or contains incorrect logger readings.")
    return score


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python grader.py path/to/solution.py")
    print(json.dumps(grade(Path(sys.argv[1]).resolve()), indent=2))

