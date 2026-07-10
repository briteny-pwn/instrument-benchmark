"""Grader for the PyVISA AWG ASCII upload instance."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import tempfile
from pathlib import Path
from types import ModuleType

import trace_pyvisa


EXPECTED_POINTS = [0.0, 0.25, 0.5, 0.75, 1.0]


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
        "connection": 0.0,
        "configuration": 0.0,
        "protocol_mapping": 0.0,
        "ascii_value_transfer": 0.0,
        "experiment_result": 0.0,
        "cleanup": 0.0,
    }

    if any(event.kind == "open_resource" and event.payload.get("resource_name") == trace_pyvisa.RESOURCE_NAME for event in trace):
        scores["connection"] = 1.0
    else:
        feedback.append("Did not open the expected PyVISA resource.")

    attributes = {event.payload["name"]: event.payload["value"] for event in trace if event.kind == "set_attribute"}
    config_checks = [
        attributes.get("timeout") == 6000,
        attributes.get("read_termination") == "\n",
        attributes.get("write_termination") == "\n",
    ]
    scores["configuration"] = sum(config_checks) / len(config_checks)
    if scores["configuration"] < 1:
        feedback.append("Missing or incorrect timeout/read_termination/write_termination.")

    semantic = [event.payload for event in trace if event.kind == "semantic"]
    required = [
        {"action": "identify"},
        {"action": "reset"},
        {"action": "upload_waveform", "waveform": "RAMP"},
        {"action": "select_waveform", "waveform": "RAMP"},
        {"action": "set_amplitude", "value": 2.0},
        {"action": "enable_output", "value": True},
        {"action": "query_waveform"},
        {"action": "query_output"},
    ]
    scores["protocol_mapping"] = sum(_contains_semantic(semantic, item) for item in required) / len(required)
    if scores["protocol_mapping"] < 1:
        feedback.append("The semantic command trace does not match all required AWG actions.")

    ascii_events = [event.payload for event in trace if event.kind == "write_ascii_values"]
    if ascii_events:
        event = ascii_events[-1]
        checks = [
            _normalize(event.get("command", "")) == "DATA:ARB RAMP,",
            _float_list_close(event.get("values"), EXPECTED_POINTS),
        ]
        scores["ascii_value_transfer"] = sum(checks) / len(checks)
    if scores["ascii_value_transfer"] < 1:
        feedback.append("Waveform should be uploaded with write_ascii_values and the expected point list.")

    scores["experiment_result"] = _grade_result(result_from_file, feedback) if result_from_file else 0.0
    if not result_from_file:
        feedback.append("No experiment result was produced.")

    closed_resource = any(event.kind == "close_resource" for event in trace)
    closed_rm = any(event.kind == "close_resource_manager" for event in trace)
    scores["cleanup"] = (int(closed_resource) + int(closed_rm)) / 2
    if scores["cleanup"] < 1:
        feedback.append("Resource and/or ResourceManager was not closed.")

    total = sum(scores.values()) / len(scores)
    return {"scores": scores, "total": round(total, 4), "feedback": feedback, "trace": [{"kind": e.kind, "payload": e.payload} for e in trace]}


def _contains_semantic(events: list[dict], expected: dict) -> bool:
    for event in events:
        if event.get("action") != expected.get("action"):
            continue
        if all(_same_value(event.get(key), value) for key, value in expected.items()):
            return True
    return False


def _same_value(actual: object, expected: object) -> bool:
    if isinstance(expected, float):
        return math.isclose(float(actual), expected, rel_tol=0, abs_tol=1e-9)
    return actual == expected


def _grade_result(result: dict, feedback: list[str]) -> float:
    checks = [
        result.get("instrument") == "MockAWG100",
        result.get("waveform") == "RAMP",
        _float_list_close(result.get("points"), EXPECTED_POINTS),
        result.get("point_count") == len(EXPECTED_POINTS),
        math.isclose(float(result.get("amplitude_vpp", float("nan"))), 2.0, abs_tol=1e-12),
        result.get("output_enabled") is True,
    ]
    score = sum(checks) / len(checks)
    if score < 1:
        feedback.append("Experiment result is missing required values or contains incorrect AWG state.")
    return score


def _float_list_close(values: object, expected: list[float]) -> bool:
    if not isinstance(values, list) or len(values) != len(expected):
        return False
    return all(math.isclose(float(v), e, abs_tol=1e-9) for v, e in zip(values, expected))


def _normalize(command: str) -> str:
    return " ".join(command.strip().upper().split())


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python grader.py path/to/solution.py")
    print(json.dumps(grade(Path(sys.argv[1]).resolve()), indent=2))

