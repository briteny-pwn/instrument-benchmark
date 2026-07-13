"""Common grader for from-scratch raw-protocol instrument instances."""

from __future__ import annotations

import importlib.util
import builtins
import json
import math
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

from . import import_guard, raw_trace
from .raw_sim_gateway import Gateway
from .state_machine_gateway import Gateway as StateMachineGateway


DEFAULT_WEIGHTS = {
    "sim_execution": 0.15,
    "forbidden_api": 0.15,
    "interface_implementation": 0.15,
    "protocol_trace": 0.2,
    "state_transition": 0.15,
    "observation": 0.15,
    "cleanup": 0.05,
}


def grade(candidate_path: Path, spec_path: Path) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    raw_trace.reset_trace()

    feedback: list[str] = []
    forbidden_imports = import_guard.check_candidate_imports(candidate_path)
    forbidden_score = 0.0 if forbidden_imports else 1.0
    if forbidden_imports:
        feedback.append(f"Forbidden instrument/framework imports observed: {', '.join(forbidden_imports)}.")

    sim_path = spec_path.parent / spec["simulator"]
    gateway = _make_gateway(spec, sim_path)
    host, port = gateway.start()
    old_host = os.environ.get("INSTRUMENT_SIM_HOST")
    old_port = os.environ.get("INSTRUMENT_SIM_PORT")
    os.environ["INSTRUMENT_SIM_HOST"] = host
    os.environ["INSTRUMENT_SIM_PORT"] = str(port)

    execution_score = 1.0
    result: dict[str, Any] = {}
    try:
        if forbidden_imports:
            raise RuntimeError("Candidate uses forbidden instrument/framework imports")
        with _blocked_imports():
            module = _load_candidate(candidate_path)
            if not hasattr(module, "run_experiment"):
                raise RuntimeError("Candidate solution must expose run_experiment(output_path=...)")
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = Path(tmpdir) / "result.json"
                returned = module.run_experiment(str(output_path))
                if output_path.exists():
                    result = json.loads(output_path.read_text(encoding="utf-8"))
                elif isinstance(returned, dict):
                    result = returned
                else:
                    raise RuntimeError("run_experiment did not return a dict or write result.json")
    except Exception as exc:
        execution_score = 0.0
        feedback.append(f"Candidate failed while running against raw simulator gateway: {exc}")
    finally:
        if old_host is None:
            os.environ.pop("INSTRUMENT_SIM_HOST", None)
        else:
            os.environ["INSTRUMENT_SIM_HOST"] = old_host
        if old_port is None:
            os.environ.pop("INSTRUMENT_SIM_PORT", None)
        else:
            os.environ["INSTRUMENT_SIM_PORT"] = old_port
        gateway.stop()

    observation_score = _grade_observation(result, spec.get("expected_result", {}), feedback) if result else 0.0
    if not result:
        feedback.append("No experiment result was produced.")

    evidence_scores = _grade_raw_evidence(spec.get("raw_protocol", {}), feedback)
    scores = {
        "sim_execution": execution_score,
        "forbidden_api": forbidden_score,
        "observation": observation_score,
        **evidence_scores,
    }

    weights = spec.get("weights", DEFAULT_WEIGHTS)
    total = sum(scores.get(name, 0.0) * weight for name, weight in weights.items())
    return {
        "instance_id": spec.get("instance_id", spec_path.parent.name),
        "scores": scores,
        "total": round(total, 4),
        "feedback": feedback,
        "result": result,
        "trace": raw_trace.serializable_trace(),
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


def _make_gateway(spec: dict[str, Any], sim_path: Path) -> Any:
    if spec.get("gateway", "pyvisa_sim") == "state_machine":
        return StateMachineGateway(sim_path)
    return Gateway(sim_path)


@contextmanager
def _blocked_imports():
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):  # type: ignore[no-untyped-def]
        root = name.split(".", 1)[0]
        if level == 0 and root in import_guard.FORBIDDEN_IMPORT_ROOTS:
            raise RuntimeError(f"Forbidden instrument/framework import at runtime: {name}")
        return original_import(name, globals, locals, fromlist, level)

    builtins.__import__ = guarded_import
    try:
        yield
    finally:
        builtins.__import__ = original_import


def _grade_raw_evidence(raw_spec: dict[str, Any], feedback: list[str]) -> dict[str, float]:
    trace = raw_trace.TRACE
    scores: dict[str, float] = {}

    expected_resources = raw_spec.get("expected_resources", [])
    opened_resources = [_resource_for_handle(e.payload.get("handle")) for e in trace if e.kind == "open"]
    if expected_resources:
        scores["interface_implementation"] = (
            int(any(e.kind == "socket_connect" for e in trace))
            + int(any(e.kind == "list_resources" for e in trace) or not raw_spec.get("require_resource_discovery"))
            + int(all(resource in opened_resources for resource in expected_resources))
        ) / 3
        if scores["interface_implementation"] < 1:
            feedback.append("Raw socket connection, discovery, or expected resource opening was incomplete.")
    else:
        scores["interface_implementation"] = 1.0 if any(e.kind == "socket_connect" for e in trace) else 0.0

    expected_commands = raw_spec.get("expected_commands", [])
    if expected_commands:
        checks = [_match_command(expectation, trace) for expectation in expected_commands]
        scores["protocol_trace"] = sum(checks) / len(checks)
        if scores["protocol_trace"] < 1:
            feedback.append("One or more expected raw protocol commands were not observed.")
    else:
        scores["protocol_trace"] = 1.0

    expected_sequence = raw_spec.get("expected_sequence", [])
    if expected_sequence:
        scores["state_transition"] = 1.0 if _match_sequence(expected_sequence, trace) else 0.0
        if scores["state_transition"] < 1:
            feedback.append("Expected instrument state-transition command sequence was not observed.")
    else:
        scores["state_transition"] = 1.0

    opened_handles = [e.payload.get("handle") for e in trace if e.kind == "open"]
    closed_handles = [e.payload.get("handle") for e in trace if e.kind == "close"]
    closed_all = opened_handles and all(handle in closed_handles for handle in opened_handles)
    disconnected = any(e.kind == "socket_disconnect" for e in trace)
    scores["cleanup"] = (int(bool(closed_all)) + int(disconnected)) / 2
    if scores["cleanup"] < 1:
        feedback.append("All raw handles and the simulator socket should be closed.")

    return scores


def _resource_for_handle(handle: Any) -> str | None:
    for event in raw_trace.TRACE:
        if event.kind == "open" and event.payload.get("handle") == handle:
            return event.payload.get("resource")
    return None


def _match_command(expectation: dict[str, Any], trace: list[raw_trace.TraceEvent]) -> bool:
    expected_kind = expectation.get("kind")
    expected_command = expectation.get("command")
    expected_resource = expectation.get("resource")
    for event in trace:
        if expected_kind and event.kind != expected_kind:
            continue
        if expected_command and _normalize(event.payload.get("command", "")) != _normalize(expected_command):
            continue
        if expected_resource and _resource_for_handle(event.payload.get("handle")) != expected_resource:
            continue
        return True
    return False


def _match_sequence(sequence: list[dict[str, Any]], trace: list[raw_trace.TraceEvent]) -> bool:
    index = 0
    for event in trace:
        if index >= len(sequence):
            return True
        if _event_matches(sequence[index], event):
            index += 1
    return index == len(sequence)


def _event_matches(expectation: dict[str, Any], event: raw_trace.TraceEvent) -> bool:
    if expectation.get("kind") and event.kind != expectation["kind"]:
        return False
    if expectation.get("command") and _normalize(event.payload.get("command", "")) != _normalize(expectation["command"]):
        return False
    if expectation.get("resource") and _resource_for_handle(event.payload.get("handle")) != expectation["resource"]:
        return False
    return True


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
        scores = [_grade_observation(actual.get(k), v, feedback, f"{path}.{k}") for k, v in expected.items()]
        return sum(scores) / len(scores)
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            feedback.append(f"Observation mismatch at {path}: expected list length {len(expected)}, got {actual!r}.")
            return 0.0
        if not expected:
            return 1.0
        scores = [_grade_observation(a, e, feedback, f"{path}[{i}]") for i, (a, e) in enumerate(zip(actual, expected))]
        return sum(scores) / len(scores)
    ok = _values_close(actual, expected)
    if not ok:
        feedback.append(f"Observation mismatch at {path}: expected {expected!r}, got {actual!r}.")
    return 1.0 if ok else 0.0


def _match_expected(actual: Any, expected: dict[str, Any]) -> bool:
    if "equals" in expected:
        return actual == expected["equals"]
    if "close" in expected:
        return _float_close(actual, expected["close"], expected.get("abs_tol", 1e-6))
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


def _normalize(command: str) -> str:
    return " ".join(str(command).strip().upper().split())
