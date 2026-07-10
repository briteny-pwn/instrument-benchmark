"""Spec-driven observation grader for instrument access instances."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

from . import trace_pyvisa


DEFAULT_WEIGHTS = {
    "pyvisa_sim_execution": 0.2,
    "observation": 0.5,
    "access": 0.2,
    "cleanup": 0.1,
}


def grade(candidate_path: Path, spec_path: Path) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    sim_backend = str((spec_path.parent / spec["simulator"]).resolve()) + "@sim"

    trace_pyvisa.reset_trace()
    trace_pyvisa.configure(sim_backend)
    trace_pyvisa.install()

    feedback: list[str] = []
    execution_score = 1.0
    result: dict[str, Any] = {}

    try:
        module = _load_candidate(candidate_path)
        if not hasattr(module, "run_experiment"):
            raise RuntimeError("Candidate solution must expose run_experiment(output_path=...)")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "result.json"
            returned = module.run_experiment(output_path)
            if output_path.exists():
                result = json.loads(output_path.read_text(encoding="utf-8"))
            elif isinstance(returned, dict):
                result = returned
            else:
                raise RuntimeError("run_experiment did not return a dict or write result.json")
    except Exception as exc:
        execution_score = 0.0
        feedback.append(f"Candidate failed while running against pyvisa-sim: {exc}")

    observation_score = _grade_observation(result, spec.get("expected_result", {}), feedback) if result else 0.0
    if not result:
        feedback.append("No experiment result was produced.")

    access_scores = _grade_access(spec.get("access", {}), feedback)
    cleanup_score = access_scores.pop("cleanup")
    access_score = sum(access_scores.values()) / len(access_scores) if access_scores else 1.0

    scores = {
        "pyvisa_sim_execution": execution_score,
        "observation": observation_score,
        "access": access_score,
        "cleanup": cleanup_score,
        **{f"access_{name}": value for name, value in access_scores.items()},
    }

    weights = spec.get("weights", DEFAULT_WEIGHTS)
    total = (
        execution_score * weights.get("pyvisa_sim_execution", 0)
        + observation_score * weights.get("observation", 0)
        + access_score * weights.get("access", 0)
        + cleanup_score * weights.get("cleanup", 0)
    )

    return {
        "instance_id": spec.get("instance_id", spec_path.parent.name),
        "scores": scores,
        "total": round(total, 4),
        "feedback": feedback,
        "result": result,
        "trace": trace_pyvisa.serializable_trace(),
    }


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        raise SystemExit("Usage: python grader.py path/to/spec.json path/to/solution.py")
    report = grade(Path(args[1]).resolve(), Path(args[0]).resolve())
    print(json.dumps(report, indent=2))


def _load_candidate(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("candidate_solution", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load candidate from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _grade_observation(actual: Any, expected: Any, feedback: list[str], path: str = "$") -> float:
    if isinstance(expected, dict) and set(expected) & {"equals", "close", "range"}:
        ok = _match_expected(actual, expected)
        if not ok:
            feedback.append(f"Observation mismatch at {path}: expected {expected!r}, got {actual!r}.")
        return 1.0 if ok else 0.0

    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            feedback.append(f"Observation mismatch at {path}: expected object, got {type(actual).__name__}.")
            return 0.0
        if not expected:
            return 1.0
        scores = [
            _grade_observation(actual.get(key), value, feedback, f"{path}.{key}")
            for key, value in expected.items()
        ]
        return sum(scores) / len(scores)

    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            feedback.append(f"Observation mismatch at {path}: expected list length {len(expected)}, got {actual!r}.")
            return 0.0
        if not expected:
            return 1.0
        scores = [
            _grade_observation(a, e, feedback, f"{path}[{idx}]")
            for idx, (a, e) in enumerate(zip(actual, expected))
        ]
        return sum(scores) / len(scores)

    ok = _values_close(actual, expected)
    if not ok:
        feedback.append(f"Observation mismatch at {path}: expected {expected!r}, got {actual!r}.")
    return 1.0 if ok else 0.0


def _match_expected(actual: Any, expected: dict[str, Any]) -> bool:
    if "equals" in expected:
        return actual == expected["equals"]
    if "close" in expected:
        target = expected["close"]
        tol = expected.get("abs_tol", 1e-6)
        return _float_close(actual, target, tol)
    if "range" in expected:
        low, high = expected["range"]
        try:
            value = float(actual)
        except (TypeError, ValueError):
            return False
        return low <= value <= high
    return False


def _values_close(actual: Any, expected: Any) -> bool:
    if isinstance(expected, float):
        return _float_close(actual, expected, 1e-6)
    return actual == expected


def _float_close(actual: Any, expected: float, abs_tol: float) -> bool:
    try:
        return math.isclose(float(actual), float(expected), rel_tol=0, abs_tol=abs_tol)
    except (TypeError, ValueError):
        return False


def _grade_access(access_spec: dict[str, Any], feedback: list[str]) -> dict[str, float]:
    trace = trace_pyvisa.TRACE
    scores: dict[str, float] = {}

    if access_spec.get("require_resource_discovery"):
        scores["resource_discovery"] = 1.0 if any(e.kind == "list_resources" for e in trace) else 0.0
        if scores["resource_discovery"] < 1:
            feedback.append("Resource discovery was expected but list_resources was not observed.")

    expected_resources = access_spec.get("expected_resources", [])
    if expected_resources:
        opened = {e.payload.get("resource_name") for e in trace if e.kind == "open_resource"}
        scores["connection"] = sum(resource in opened for resource in expected_resources) / len(expected_resources)
        if scores["connection"] < 1:
            feedback.append("Not all expected resources were opened.")

    communication = access_spec.get("communication")
    if expected_resources and communication:
        checks: list[bool] = []
        for resource in expected_resources:
            attrs = {
                e.payload.get("name"): e.payload.get("value")
                for e in trace
                if e.kind == "set_attribute" and e.payload.get("resource_name") == resource
            }
            checks.extend(attrs.get(name) == value for name, value in communication.items())
        scores["configuration"] = sum(checks) / len(checks)
        if scores["configuration"] < 1:
            feedback.append("One or more expected resources missed required communication configuration.")

    transfer_expectations = access_spec.get("transfer_expectations", [])
    if transfer_expectations:
        checks = [_match_trace_event(expectation, trace) for expectation in transfer_expectations]
        scores["value_transfer"] = sum(checks) / len(checks)
        if scores["value_transfer"] < 1:
            feedback.append("One or more expected PyVISA value transfer helpers were not observed.")

    opened_resources = [e.payload.get("resource_name") for e in trace if e.kind == "open_resource"]
    closed_resources = [e.payload.get("resource_name") for e in trace if e.kind == "close_resource"]
    closed_all = opened_resources and all(resource in closed_resources for resource in opened_resources)
    closed_rm = any(e.kind == "close_resource_manager" for e in trace)
    scores["cleanup"] = (int(bool(closed_all)) + int(closed_rm)) / 2
    if scores["cleanup"] < 1:
        feedback.append("All opened resources and the ResourceManager should be closed.")

    return scores


def _match_trace_event(expectation: dict[str, Any], trace: list[trace_pyvisa.TraceEvent]) -> bool:
    for event in trace:
        if event.kind != expectation.get("kind"):
            continue
        payload = event.payload
        if expectation.get("resource_name") and payload.get("resource_name") != expectation["resource_name"]:
            continue
        if expectation.get("command") and _normalize(payload.get("command", "")) != _normalize(expectation["command"]):
            continue
        if "values" in expectation and not _list_close(payload.get("values"), expectation["values"]):
            continue
        expected_kwargs = expectation.get("kwargs", {})
        kwargs = payload.get("kwargs", {})
        if any(kwargs.get(key) != value for key, value in expected_kwargs.items()):
            continue
        return True
    return False


def _list_close(actual: Any, expected: list[Any]) -> bool:
    if not isinstance(actual, list) or len(actual) != len(expected):
        return False
    return all(_values_close(a, e) for a, e in zip(actual, expected))


def _normalize(command: str) -> str:
    return " ".join(command.strip().upper().split())

