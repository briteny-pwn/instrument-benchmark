"""Common grader for from-scratch raw-protocol instrument instances."""

from __future__ import annotations

import importlib.util
import builtins
import copy
import json
import math
import os
import re
import statistics
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

from . import import_guard, raw_trace
from .raw_sim_gateway import Gateway
from .coupled_signal_gateway import Gateway as CoupledSignalGateway
from .linear_sweep_gateway import Gateway as LinearSweepGateway
from .state_machine_gateway import Gateway as StateMachineGateway
from .yaq_native_gateway import Gateway as YaqNativeGateway


DEFAULT_WEIGHTS = {
    "sim_execution": 0.15,
    "forbidden_api": 0.15,
    "interface_implementation": 0.15,
    "protocol_trace": 0.2,
    "state_transition": 0.15,
    "observation": 0.15,
    "cleanup": 0.05,
}


DEFAULT_V2_RUBRIC = {
    "sim_execution": 0.05,
    "forbidden_api": 0.10,
    "task_success": 0.30,
    "instrument_access": 0.15,
    "protocol_correctness": 0.15,
    "state_process": 0.15,
    "safety_and_cleanup": 0.10,
}


def grade(candidate_path: Path, spec_path: Path) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if spec.get("scenarios"):
        return _grade_scenario_suite(candidate_path, spec_path, spec)
    return _grade_single(candidate_path, spec_path, spec)


def _grade_single(candidate_path: Path, spec_path: Path, spec: dict[str, Any]) -> dict[str, Any]:
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
    sim_state: dict[str, Any] = {}
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
        sim_state = _snapshot_gateway(gateway)
        if old_host is None:
            os.environ.pop("INSTRUMENT_SIM_HOST", None)
        else:
            os.environ["INSTRUMENT_SIM_HOST"] = old_host
        if old_port is None:
            os.environ.pop("INSTRUMENT_SIM_PORT", None)
        else:
            os.environ["INSTRUMENT_SIM_PORT"] = old_port
        gateway.stop()

    if spec.get("spec_version") == 2:
        return _grade_v2(
            spec=spec,
            execution_score=execution_score,
            forbidden_score=forbidden_score,
            result=result,
            feedback=feedback,
            sim_state=sim_state,
        )

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
        "pass": round(total, 4) >= spec.get("pass_threshold", 0.8),
        "feedback": feedback,
        "result": result,
        "trace": raw_trace.serializable_trace(),
        "sim_state": sim_state,
    }


def _grade_scenario_suite(candidate_path: Path, spec_path: Path, spec: dict[str, Any]) -> dict[str, Any]:
    scenario_reports: list[dict[str, Any]] = []
    repetitions = max(1, int(spec.get("suite", {}).get("repetitions", 1)))
    for index, scenario in enumerate(spec["scenarios"]):
        scenario_id = scenario.get("id", f"scenario-{index + 1}")
        for repetition in range(1, repetitions + 1):
            scenario_spec = _build_scenario_spec(spec, scenario)
            report = _grade_single(candidate_path, spec_path, scenario_spec)
            report["scenario_id"] = scenario_id
            report["repetition"] = repetition
            report["run_id"] = f"{scenario_id}#{repetition}" if repetitions > 1 else scenario_id
            scenario_reports.append(report)

    return aggregate_scenario_reports(spec, scenario_reports)


def aggregate_scenario_reports(
    spec: dict[str, Any], scenario_reports: list[dict[str, Any]]
) -> dict[str, Any]:
    """Aggregate already-scored isolated scenario runs into the standard suite report."""
    repetitions = max(1, int(spec.get("suite", {}).get("repetitions", 1)))
    dimension_names = sorted({name for report in scenario_reports for name in report.get("scores", {})})
    scores = {
        name: sum(float(report.get("scores", {}).get(name, 0.0)) for report in scenario_reports) / len(scenario_reports)
        for name in dimension_names
    }
    pass_count = sum(bool(report.get("pass")) for report in scenario_reports)
    pass_rate = pass_count / len(scenario_reports)
    scores["robustness"] = pass_rate

    suite = spec.get("suite", {})
    robustness_weight = float(suite.get("robustness_weight", 0.25))
    mean_scenario_total = sum(float(report.get("total", 0.0)) for report in scenario_reports) / len(scenario_reports)
    total = round((1.0 - robustness_weight) * mean_scenario_total + robustness_weight * pass_rate, 4)
    minimum_pass_rate = float(suite.get("minimum_pass_rate", 1.0))
    pass_threshold = float(spec.get("pass_threshold", 0.8))
    passed = total >= pass_threshold and pass_rate >= minimum_pass_rate

    feedback = [
        f"{report['run_id']}: {message}"
        for report in scenario_reports
        for message in report.get("feedback", [])
    ]
    if pass_rate < minimum_pass_rate:
        feedback.append(
            f"Scenario pass rate {pass_rate:.3f} is below the required minimum {minimum_pass_rate:.3f}."
        )

    reliability = _build_reliability_report(scenario_reports)

    return {
        "instance_id": spec.get("instance_id", "unknown"),
        "spec_version": spec.get("spec_version", 2),
        "evaluation_mode": "scenario_suite",
        "scores": scores,
        "total": total,
        "pass": passed,
        "pass_rate": pass_rate,
        "scenario_count": len(scenario_reports),
        "unique_scenario_count": len(spec["scenarios"]),
        "repetitions_per_scenario": repetitions,
        "reliability": reliability,
        "feedback": feedback,
        "scenarios": scenario_reports,
    }


def grade_collected_scenario(
    *,
    spec: dict[str, Any],
    result: dict[str, Any],
    trace: list[dict[str, Any]],
    sim_state: dict[str, Any],
    execution_score: float,
    forbidden_score: float,
    feedback: list[str] | None = None,
) -> dict[str, Any]:
    """Score evidence produced outside the grader process by an isolated runner."""
    raw_trace.load_serializable_trace(trace)
    messages = list(feedback or [])
    if spec.get("spec_version") == 2:
        return _grade_v2(
            spec=spec,
            execution_score=execution_score,
            forbidden_score=forbidden_score,
            result=result,
            feedback=messages,
            sim_state=sim_state,
        )
    observation_score = _grade_observation(result, spec.get("expected_result", {}), messages) if result else 0.0
    scores = {
        "sim_execution": execution_score,
        "forbidden_api": forbidden_score,
        "observation": observation_score,
        **_grade_raw_evidence(spec.get("raw_protocol", {}), messages),
    }
    weights = spec.get("weights", DEFAULT_WEIGHTS)
    total = round(sum(scores.get(name, 0.0) * weight for name, weight in weights.items()), 4)
    return {
        "instance_id": spec.get("instance_id"),
        "scores": scores,
        "total": total,
        "pass": total >= spec.get("pass_threshold", 0.8),
        "feedback": messages,
        "result": result,
        "trace": raw_trace.serializable_trace(),
        "sim_state": sim_state,
    }


def _build_reliability_report(reports: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for report in reports:
        grouped.setdefault(str(report.get("scenario_id", "unknown")), []).append(report)
    return {
        "method": "descriptive totals with normal-approximate mean CI and Wilson pass-rate CI",
        "overall": _summarize_runs(reports),
        "by_scenario": {
            scenario_id: _summarize_runs(items) for scenario_id, items in grouped.items()
        },
    }


def _summarize_runs(reports: list[dict[str, Any]]) -> dict[str, Any]:
    totals = [float(report.get("total", 0.0)) for report in reports]
    count = len(totals)
    successes = sum(bool(report.get("pass")) for report in reports)
    if not totals:
        return {
            "run_count": 0,
            "mean_total": None,
            "stdev_total": None,
            "mean_total_ci95": None,
            "pass_rate": None,
            "pass_rate_wilson_ci95": None,
        }
    mean = statistics.mean(totals)
    stdev = statistics.stdev(totals) if count >= 2 else 0.0
    margin = 1.96 * stdev / math.sqrt(count) if count >= 2 else 0.0
    return {
        "run_count": count,
        "mean_total": round(mean, 6),
        "stdev_total": round(stdev, 6),
        "min_total": round(min(totals), 6),
        "max_total": round(max(totals), 6),
        "mean_total_ci95": [round(max(0.0, mean - margin), 6), round(min(1.0, mean + margin), 6)],
        "pass_rate": round(successes / count, 6),
        "pass_rate_wilson_ci95": [round(value, 6) for value in _wilson_interval(successes, count)],
    }


def _wilson_interval(successes: int, count: int, z: float = 1.96) -> tuple[float, float]:
    if count <= 0:
        return (0.0, 0.0)
    proportion = successes / count
    denominator = 1.0 + z * z / count
    center = (proportion + z * z / (2.0 * count)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1.0 - proportion) / count + z * z / (4.0 * count * count))
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _build_scenario_spec(spec: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    scenario_spec = copy.deepcopy(spec)
    scenario_spec.pop("scenarios", None)
    scenario_spec.pop("suite", None)
    scenario_spec["simulator"] = scenario["simulator"]
    if scenario.get("spec_overrides"):
        _deep_update(scenario_spec, scenario["spec_overrides"])
    if "pass_threshold" in scenario:
        scenario_spec["pass_threshold"] = scenario["pass_threshold"]

    overrides = scenario.get("check_overrides", {})
    for check in scenario_spec.get("checks", []):
        override = overrides.get(check.get("name"))
        if override:
            _deep_update(check, override)
    return scenario_spec


def _deep_update(target: dict[str, Any], override: dict[str, Any]) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


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
    gateway = spec.get("gateway", "pyvisa_sim")
    if gateway == "state_machine":
        return StateMachineGateway(sim_path)
    if gateway == "yaq_native":
        return YaqNativeGateway(sim_path)
    if gateway == "coupled_signal":
        return CoupledSignalGateway(sim_path)
    if gateway == "linear_sweep":
        return LinearSweepGateway(sim_path)
    return Gateway(
        sim_path,
        snapshot_queries=spec.get("snapshot_queries"),
        intercepted_write_patterns=spec.get("intercepted_write_patterns"),
        write_rewrites=spec.get("write_rewrites"),
        query_guards=spec.get("query_guards"),
    )


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
        matched_sequence, missing_sequence = _match_sequence_coverage(expected_sequence, trace)
        scores["state_transition"] = matched_sequence / len(expected_sequence)
        if scores["state_transition"] < 1:
            feedback.append(
                f"Expected instrument state-transition sequence was partially observed "
                f"({matched_sequence}/{len(expected_sequence)} milestones matched)."
            )
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


def _grade_v2(
    *,
    spec: dict[str, Any],
    execution_score: float,
    forbidden_score: float,
    result: dict[str, Any],
    feedback: list[str],
    sim_state: dict[str, Any],
) -> dict[str, Any]:
    scores = {
        "sim_execution": execution_score,
        "forbidden_api": forbidden_score,
        "task_success": 0.0,
        "instrument_access": 0.0,
        "protocol_correctness": 0.0,
        "state_process": 0.0,
        "safety_and_cleanup": 0.0,
    }
    buckets: dict[str, list[float]] = {name: [] for name in scores}
    evidence: list[dict[str, Any]] = []

    if not result:
        feedback.append("No experiment result was produced.")

    for check in spec.get("checks", []):
        dimension = check.get("dimension", _default_dimension_for_check(check.get("type")))
        score, detail = _run_v2_check(check, result, sim_state, feedback)
        detail["dimension"] = dimension
        evidence.append(detail)
        buckets.setdefault(dimension, []).append(score)

    for dimension, values in buckets.items():
        if values:
            scores[dimension] = sum(values) / len(values)

    rubric = spec.get("rubric", DEFAULT_V2_RUBRIC)
    total = sum(scores.get(name, 0.0) * weight for name, weight in rubric.items())
    total = round(total, 4)
    gate_failures = _evaluate_gates(spec.get("gates", []), scores, evidence)
    for failure in gate_failures:
        feedback.append(f"Required gate failed: {failure}.")
    return {
        "instance_id": spec.get("instance_id"),
        "spec_version": 2,
        "scores": scores,
        "total": total,
        "pass": total >= spec.get("pass_threshold", 0.8) and not gate_failures,
        "gate_failures": gate_failures,
        "feedback": feedback,
        "evidence": evidence,
        "result": result,
        "trace": raw_trace.serializable_trace(),
        "sim_state": sim_state,
    }


def _run_v2_check(
    check: dict[str, Any],
    result: dict[str, Any],
    sim_state: dict[str, Any],
    feedback: list[str],
) -> tuple[float, dict[str, Any]]:
    check_type = check.get("type")
    name = check.get("name", check_type)
    if check_type == "result_json":
        local_feedback: list[str] = []
        score = _grade_observation(result, check.get("expected", {}), local_feedback) if result else 0.0
        feedback.extend(f"{name}: {item}" for item in local_feedback)
        return score, {"name": name, "type": check_type, "score": score, "messages": local_feedback}
    if check_type == "sim_state":
        local_feedback = []
        actual = _get_path(sim_state, check.get("path", "$"))
        score = _grade_observation(actual, check.get("expected"), local_feedback, check.get("path", "$"))
        feedback.extend(f"{name}: {item}" for item in local_feedback)
        return score, {"name": name, "type": check_type, "score": score, "actual": actual}
    if check_type == "sim_state_all":
        collection = _get_path(sim_state, check.get("path", "$.resources"))
        items = list(collection.values()) if isinstance(collection, dict) else list(collection or [])
        item_path = check.get("item_path", "$.")
        actual_values = [_get_path(item, item_path) for item in items]
        local_feedback = []
        item_scores = [
            _grade_observation(value, check.get("expected"), local_feedback, f"{check.get('path')}[*].{item_path}")
            for value in actual_values
        ]
        score = sum(item_scores) / len(item_scores) if item_scores else 0.0
        feedback.extend(f"{name}: {item}" for item in local_feedback)
        return score, {
            "name": name,
            "type": check_type,
            "score": score,
            "actual": actual_values,
            "item_count": len(items),
        }
    if check_type == "trace_coverage":
        expectations = check.get("expectations", [])
        matched = [item for item in expectations if _match_command(item, raw_trace.TRACE)]
        missing = [item for item in expectations if not _match_command(item, raw_trace.TRACE)]
        score = len(matched) / len(expectations) if expectations else 1.0
        if score < 1:
            feedback.append(f"{name}: trace coverage matched {len(matched)}/{len(expectations)} expectations.")
        return score, {"name": name, "type": check_type, "score": score, "matched": matched, "missing": missing}
    if check_type == "ordered_milestones":
        milestones = check.get("milestones", [])
        matched_count, missing = _match_sequence_coverage(milestones, raw_trace.TRACE)
        score = matched_count / len(milestones) if milestones else 1.0
        if score < 1:
            feedback.append(f"{name}: ordered milestones matched {matched_count}/{len(milestones)}.")
        return score, {"name": name, "type": check_type, "score": score, "matched_count": matched_count, "missing": missing}
    if check_type == "causal_order":
        score, detail = _grade_causal_order(check)
        if score < 1:
            feedback.append(
                f"{name}: causal ordering satisfied {detail['matched_count']}/{detail['constraint_count']} constraints."
            )
        detail.update({"name": name, "type": check_type, "score": score})
        return score, detail
    if check_type == "anti_hardcode":
        score, detail = _grade_anti_hardcode(check)
        if score < 1:
            feedback.append(f"{name}: simulator interaction evidence is insufficient.")
        detail.update({"name": name, "type": check_type, "score": score})
        return score, detail
    if check_type == "cleanup":
        score, detail = _grade_cleanup()
        if score < 1:
            feedback.append(f"{name}: all raw handles and simulator sockets should be closed.")
        detail.update({"name": name, "type": check_type, "score": score})
        return score, detail
    if check_type == "result_trace_binding":
        result_value = _get_path(result, check.get("result_path", "$"))
        event_kind = check.get("event_kind", "open")
        payload_field = check.get("payload_field", "resource")
        observed = [
            event.payload.get(payload_field)
            for event in raw_trace.TRACE
            if event.kind == event_kind
        ]
        score = 1.0 if result_value in observed else 0.0
        if score < 1:
            feedback.append(f"{name}: result value is not bound to observed simulator evidence.")
        return score, {
            "name": name,
            "type": check_type,
            "score": score,
            "result_value": result_value,
            "observed": observed,
        }
    if check_type == "result_sim_state_binding":
        result_value = _get_path(result, check.get("result_path", "$"))
        state_value = _get_path(sim_state, check.get("sim_path", "$"))
        tolerance = float(check.get("abs_tol", 1e-9))
        if isinstance(state_value, (int, float)) and not isinstance(state_value, bool):
            matched = not isinstance(result_value, bool) and _float_close(result_value, state_value, tolerance)
        else:
            matched = result_value == state_value
        score = 1.0 if matched else 0.0
        if score < 1:
            feedback.append(f"{name}: reported value does not match hidden simulator state.")
        return score, {
            "name": name,
            "type": check_type,
            "score": score,
            "result_value": result_value,
            "state_value": state_value,
        }
    if check_type == "trace_numeric_aggregate":
        score, detail = _grade_trace_numeric_aggregate(check, result)
        if score < 1:
            feedback.append(f"{name}: reported statistics do not match values independently reconstructed from trace.")
        detail.update({"name": name, "type": check_type, "score": score})
        return score, detail
    if check_type == "trace_numeric_array":
        score, detail = _grade_trace_numeric_array(check, result)
        if score < 1:
            feedback.append(f"{name}: reported array/statistics do not match the hidden instrument response.")
        detail.update({"name": name, "type": check_type, "score": score})
        return score, detail
    if check_type == "trace_string_array":
        score, detail = _grade_trace_string_array(check, result)
        if score < 1:
            feedback.append(f"{name}: reported string history does not match simulator responses.")
        detail.update({"name": name, "type": check_type, "score": score})
        return score, detail
    if check_type == "trace_ieee_block":
        score, detail = _grade_trace_ieee_block(check, result)
        if score < 1:
            feedback.append(f"{name}: reported waveform does not match the hidden IEEE block payload.")
        detail.update({"name": name, "type": check_type, "score": score})
        return score, detail
    if check_type == "trace_xy_spectrum":
        score, detail = _grade_trace_xy_spectrum(check, result)
        if score < 1:
            feedback.append(f"{name}: reported spectrum summary does not match hidden wavelength/count arrays.")
        detail.update({"name": name, "type": check_type, "score": score})
        return score, detail
    if check_type == "trace_command_numeric_array":
        score, detail = _grade_trace_command_numeric_array(check, result)
        if score < 1:
            feedback.append(f"{name}: uploaded numeric payload does not match the task or reported result.")
        detail.update({"name": name, "type": check_type, "score": score})
        return score, detail
    if check_type == "trace_response":
        score, detail = _grade_trace_response(check, result)
        if score < 1:
            feedback.append(f"{name}: reported value does not match the observed instrument response.")
        detail.update({"name": name, "type": check_type, "score": score})
        return score, detail
    if check_type == "result_threshold_decision":
        score, detail = _grade_result_threshold_decision(check, result)
        if score < 1:
            feedback.append(f"{name}: reported decision does not follow the documented thresholds.")
        detail.update({"name": name, "type": check_type, "score": score})
        return score, detail
    if check_type == "result_pairwise_max_abs_error":
        score, detail = _grade_result_pairwise_max_abs_error(check, result)
        if score < 1:
            feedback.append(f"{name}: reported maximum error does not match the two observed arrays.")
        detail.update({"name": name, "type": check_type, "score": score})
        return score, detail
    if check_type == "result_pairwise_differences":
        score, detail = _grade_result_pairwise_differences(check, result)
        if score < 1:
            feedback.append(f"{name}: reported pointwise differences do not match the observed arrays.")
        detail.update({"name": name, "type": check_type, "score": score})
        return score, detail
    if check_type == "result_linear_fit":
        score, detail = _grade_result_linear_fit(check, result)
        if score < 1:
            feedback.append(f"{name}: reported fit does not match the observed sweep arrays.")
        detail.update({"name": name, "type": check_type, "score": score})
        return score, detail
    if check_type == "result_endpoint_slope":
        score, detail = _grade_result_endpoint_slope(check, result)
        if score < 1:
            feedback.append(f"{name}: reported endpoint slope does not match the observed arrays.")
        detail.update({"name": name, "type": check_type, "score": score})
        return score, detail
    if check_type == "result_mean_deviation_validation":
        score, detail = _grade_result_mean_deviation_validation(check, result)
        if score < 1:
            feedback.append(f"{name}: validation decision does not match independently derived sensor statistics.")
        detail.update({"name": name, "type": check_type, "score": score})
        return score, detail
    if check_type == "result_argmax_x":
        score, detail = _grade_result_argmax_x(check, result)
        if score < 1:
            feedback.append(f"{name}: reported best position does not match the observed maximum signal.")
        detail.update({"name": name, "type": check_type, "score": score})
        return score, detail
    feedback.append(f"{name}: unsupported v2 check type {check_type!r}.")
    return 0.0, {"name": name, "type": check_type, "score": 0.0, "error": "unsupported check type"}


def _default_dimension_for_check(check_type: str | None) -> str:
    return {
        "result_json": "task_success",
        "sim_state": "task_success",
        "sim_state_all": "task_success",
        "trace_coverage": "protocol_correctness",
        "ordered_milestones": "state_process",
        "causal_order": "state_process",
        "anti_hardcode": "instrument_access",
        "cleanup": "safety_and_cleanup",
        "result_trace_binding": "task_success",
        "result_sim_state_binding": "task_success",
        "trace_numeric_aggregate": "task_success",
        "trace_numeric_array": "task_success",
        "trace_string_array": "task_success",
        "trace_ieee_block": "task_success",
        "trace_xy_spectrum": "task_success",
        "trace_command_numeric_array": "task_success",
        "trace_response": "task_success",
        "result_threshold_decision": "task_success",
        "result_pairwise_max_abs_error": "task_success",
        "result_pairwise_differences": "task_success",
        "result_linear_fit": "task_success",
        "result_endpoint_slope": "task_success",
        "result_mean_deviation_validation": "task_success",
        "result_argmax_x": "task_success",
    }.get(check_type, "task_success")


def _evaluate_gates(
    gates: list[dict[str, Any]], scores: dict[str, float], evidence: list[dict[str, Any]]
) -> list[str]:
    evidence_by_name = {item.get("name"): item for item in evidence}
    failures: list[str] = []
    for gate in gates:
        minimum = float(gate.get("min", 1.0))
        if "dimension" in gate:
            label = f"dimension {gate['dimension']}"
            actual = float(scores.get(gate["dimension"], 0.0))
        elif "check" in gate:
            label = f"check {gate['check']}"
            actual = float(evidence_by_name.get(gate["check"], {}).get("score", 0.0))
        else:
            failures.append("invalid gate without dimension or check")
            continue
        if actual < minimum:
            failures.append(f"{label} scored {actual:.3f}, requires {minimum:.3f}")
    return failures


def _resource_for_handle(handle: Any) -> str | None:
    for event in raw_trace.TRACE:
        if event.kind == "open" and event.payload.get("handle") == handle:
            return event.payload.get("resource")
    return None


def _match_command(expectation: dict[str, Any], trace: list[raw_trace.TraceEvent]) -> bool:
    return any(_event_matches(expectation, event) for event in trace)


def _match_sequence(sequence: list[dict[str, Any]], trace: list[raw_trace.TraceEvent]) -> bool:
    index = 0
    for event in trace:
        if index >= len(sequence):
            return True
        if _event_matches(sequence[index], event):
            index += 1
    return index == len(sequence)


def _match_sequence_coverage(
    sequence: list[dict[str, Any]], trace: list[raw_trace.TraceEvent]
) -> tuple[int, list[dict[str, Any]]]:
    index = 0
    missing: list[dict[str, Any]] = []
    for event in trace:
        if index >= len(sequence):
            break
        if _event_matches(sequence[index], event):
            index += 1
    if index < len(sequence):
        missing = sequence[index:]
    return index, missing


def _grade_causal_order(check: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for index, constraint in enumerate(check.get("constraints", []), start=1):
        before_occurrence = constraint.get("before_occurrence", "first")
        after_occurrence = constraint.get("after_occurrence", "first")
        before_indices = [
            event_index
            for event_index, event in enumerate(raw_trace.TRACE)
            if _event_matches(constraint.get("before", {}), event)
        ]
        after_indices = [
            event_index
            for event_index, event in enumerate(raw_trace.TRACE)
            if _event_matches(constraint.get("after", {}), event)
        ]
        before_index = _select_occurrence(before_indices, before_occurrence)
        after_index = _select_occurrence(after_indices, after_occurrence)
        matched = before_index is not None and after_index is not None and before_index < after_index
        details.append(
            {
                "label": constraint.get("label", f"constraint-{index}"),
                "before": constraint.get("before", {}),
                "after": constraint.get("after", {}),
                "before_occurrence": before_occurrence,
                "after_occurrence": after_occurrence,
                "before_index": before_index,
                "after_index": after_index,
                "matched": matched,
            }
        )
    matched_count = sum(int(item["matched"]) for item in details)
    score = matched_count / len(details) if details else 1.0
    return score, {
        "matched_count": matched_count,
        "constraint_count": len(details),
        "constraints": details,
    }


def _select_occurrence(indices: list[int], occurrence: str) -> int | None:
    if not indices:
        return None
    if occurrence == "first":
        return indices[0]
    if occurrence == "last":
        return indices[-1]
    return None


def _event_matches(expectation: dict[str, Any], event: raw_trace.TraceEvent) -> bool:
    if expectation.get("kind") and event.kind != expectation["kind"]:
        return False
    if expectation.get("command") and _normalize(event.payload.get("command", "")) != _normalize(expectation["command"]):
        return False
    if expectation.get("command_regex") and not re.fullmatch(
        expectation["command_regex"], _normalize(event.payload.get("command", ""))
    ):
        return False
    if expectation.get("command_prefix") and not _normalize(event.payload.get("command", "")).startswith(
        _normalize(expectation["command_prefix"])
    ):
        return False
    if expectation.get("resource") and _resource_for_handle(event.payload.get("handle")) != expectation["resource"]:
        return False
    if expectation.get("payload_equals") and any(
        event.payload.get(key) != value for key, value in expectation["payload_equals"].items()
    ):
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
    if isinstance(actual, bool) or isinstance(expected, bool):
        return False
    try:
        return math.isclose(float(actual), float(expected), rel_tol=0, abs_tol=abs_tol)
    except (TypeError, ValueError):
        return False


def _normalize(command: str) -> str:
    return " ".join(str(command).strip().upper().split())


def _grade_cleanup() -> tuple[float, dict[str, Any]]:
    opened_handles = [event.payload.get("handle") for event in raw_trace.TRACE if event.kind == "open"]
    closed_handles = [event.payload.get("handle") for event in raw_trace.TRACE if event.kind == "close"]
    closed_all = bool(opened_handles) and all(handle in closed_handles for handle in opened_handles)
    disconnected = any(event.kind == "socket_disconnect" for event in raw_trace.TRACE)
    score = (int(closed_all) + int(disconnected)) / 2
    return score, {"opened_handles": opened_handles, "closed_handles": closed_handles, "socket_disconnected": disconnected}


def _grade_anti_hardcode(check: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    requirements = check.get("requires", ["socket_connect", "query"])
    observed = {event.kind for event in raw_trace.TRACE}
    matched = [kind for kind in requirements if kind in observed]
    score = len(matched) / len(requirements) if requirements else 1.0
    return score, {"requires": requirements, "matched": matched, "missing": [kind for kind in requirements if kind not in observed]}


def _grade_trace_numeric_aggregate(
    check: dict[str, Any], result: dict[str, Any]
) -> tuple[float, dict[str, Any]]:
    selector = check.get("selector", {})
    response_pattern = re.compile(check["response_regex"])
    group: int | str = check.get("value_group", 1)
    values: list[float] = []
    for event in raw_trace.TRACE:
        if not _event_matches(selector, event):
            continue
        match = response_pattern.search(str(event.payload.get("response", "")))
        if match is None:
            continue
        try:
            values.append(float(match.group(group)))
        except (IndexError, TypeError, ValueError):
            continue

    return _grade_numeric_assertions(check, result, values)


def _grade_trace_numeric_array(check: dict[str, Any], result: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    selector = check.get("selector", {})
    delimiter = str(check.get("delimiter", ","))
    values: list[float] = []
    responses: list[str] = []
    for event in raw_trace.TRACE:
        if not _event_matches(selector, event):
            continue
        response = str(event.payload.get("response", "")).strip()
        responses.append(response)
        try:
            values.extend(float(item.strip()) for item in response.split(delimiter) if item.strip())
        except ValueError:
            continue
    score, detail = _grade_numeric_assertions(check, result, values)
    detail["responses"] = responses
    return score, detail


def _grade_trace_string_array(
    check: dict[str, Any], result: dict[str, Any]
) -> tuple[float, dict[str, Any]]:
    selector = check.get("selector", {})
    pattern = re.compile(check["response_regex"]) if check.get("response_regex") else None
    values: list[str] = []
    for event in raw_trace.TRACE:
        if not _event_matches(selector, event):
            continue
        response = str(event.payload.get("response", "")).strip()
        if pattern is None:
            values.append(response)
            continue
        match = pattern.search(response)
        if match is not None:
            values.append(str(match.group(check.get("group", 1))))
    reported = _get_path(result, check["result_path"])
    matched = bool(values) and reported == values
    return (1.0 if matched else 0.0), {
        "values": values,
        "reported": reported,
        "matched": matched,
    }


def _grade_trace_ieee_block(check: dict[str, Any], result: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    selector = check.get("selector", {})
    payloads: list[bytes] = []
    parse_errors: list[str] = []
    for event in raw_trace.TRACE:
        if not _event_matches(selector, event):
            continue
        response = str(event.payload.get("response", "")).encode("latin-1")
        try:
            payloads.append(_parse_ieee_block_payload(response))
        except ValueError as exc:
            parse_errors.append(str(exc))

    payload = payloads[-1] if payloads else b""
    if check.get("signed"):
        raw_codes = [value - 256 if value >= 128 else value for value in payload]
    else:
        raw_codes = list(payload)
    scale = float(check.get("scale", 1.0))
    offset = float(check.get("offset", 0.0))
    zero = float(check.get("zero", 0.0))
    voltages = [(code - offset) * scale + zero for code in raw_codes]

    derived_values: dict[str, Any] = {
        "raw_values": raw_codes,
        "count": len(raw_codes),
        "scaled_values": voltages,
        "scaled_mean": statistics.mean(voltages) if voltages else None,
        "scaled_peak_to_peak": max(voltages) - min(voltages) if voltages else None,
    }
    assertion_results: list[dict[str, Any]] = []
    matched_count = 0
    for assertion in check.get("assertions", []):
        operation = assertion["derived"]
        derived = derived_values.get(operation)
        actual = _get_path(result, assertion["result_path"])
        tolerance = float(assertion.get("abs_tol", 1e-9))
        if isinstance(derived, list):
            matched = bool(payload) and _numeric_lists_close(actual, derived, tolerance)
        else:
            matched = bool(payload) and derived is not None and _float_close(actual, derived, tolerance)
        matched_count += int(matched)
        assertion_results.append(
            {
                "result_path": assertion["result_path"],
                "derived_operation": operation,
                "actual": actual,
                "derived": derived,
                "matched": matched,
            }
        )
    assertions = check.get("assertions", [])
    score = matched_count / len(assertions) if assertions else (1.0 if payload else 0.0)
    return score, {
        "payload_length": len(payload),
        "raw_codes": raw_codes,
        "scaled_values": voltages,
        "parse_errors": parse_errors,
        "assertions": assertion_results,
    }


def _grade_trace_xy_spectrum(
    check: dict[str, Any], result: dict[str, Any]
) -> tuple[float, dict[str, Any]]:
    def parse(selector: dict[str, Any], prefix: str) -> list[float]:
        responses = [
            str(event.payload.get("response", "")).strip()
            for event in raw_trace.TRACE
            if _event_matches(selector, event)
        ]
        if not responses:
            return []
        response = responses[-1]
        if prefix and not response.upper().startswith(prefix.upper()):
            return []
        payload = response[len(prefix) :].strip() if prefix else response
        try:
            return [float(item.strip()) for item in payload.split(str(check.get("delimiter", ","))) if item.strip()]
        except ValueError:
            return []

    xs = parse(check["x_selector"], str(check.get("x_prefix", "")))
    ys = parse(check["y_selector"], str(check.get("y_prefix", "")))
    derived: dict[str, Any] = {}
    if xs and len(xs) == len(ys):
        peak_index = max(range(len(ys)), key=ys.__getitem__)
        derived = {
            "point_count": len(ys),
            "peak_x": xs[peak_index],
            "peak_y": ys[peak_index],
            "integral": sum(ys),
        }
    assertion_results: list[dict[str, Any]] = []
    for key, result_path in check.get("result_paths", {}).items():
        actual = _get_path(result, result_path)
        expected = derived.get(key)
        if key == "point_count":
            matched = actual == expected
        else:
            matched = expected is not None and _float_close(actual, expected, float(check.get("abs_tol", 1e-9)))
        assertion_results.append(
            {"derived": key, "result_path": result_path, "actual": actual, "expected": expected, "matched": matched}
        )
    score = (
        sum(int(item["matched"]) for item in assertion_results) / len(assertion_results)
        if assertion_results and derived
        else 0.0
    )
    return score, {"x_count": len(xs), "y_count": len(ys), "derived": derived, "assertions": assertion_results}


def _grade_trace_command_numeric_array(
    check: dict[str, Any], result: dict[str, Any]
) -> tuple[float, dict[str, Any]]:
    prefix = str(check["command_prefix"])
    delimiter = str(check.get("delimiter", ","))
    parsed_commands: list[dict[str, Any]] = []
    for event in raw_trace.TRACE:
        if event.kind != check.get("kind", "write"):
            continue
        command = str(event.payload.get("command", "")).strip()
        if not command.upper().startswith(prefix.upper()):
            continue
        fields = command[len(prefix) :].split(delimiter)
        if len(fields) < 2:
            continue
        name = fields[0].strip()
        try:
            values = [float(item.strip()) for item in fields[1:] if item.strip()]
        except ValueError:
            continue
        parsed_commands.append({"command": command, "name": name, "values": values})

    parsed = parsed_commands[-1] if parsed_commands else {"name": None, "values": []}
    values = parsed["values"]
    checks: list[dict[str, Any]] = []

    def add_check(label: str, actual: Any, expected: Any, matched: bool) -> None:
        checks.append({"label": label, "actual": actual, "expected": expected, "matched": matched})

    expected_name = check.get("expected_name")
    if expected_name is not None:
        add_check("expected_name", parsed["name"], expected_name, parsed["name"] == expected_name)
    expected_values = check.get("expected_values")
    if expected_values is not None:
        add_check(
            "expected_values",
            values,
            expected_values,
            _numeric_lists_close(values, expected_values, float(check.get("abs_tol", 1e-9))),
        )
    result_name_path = check.get("result_name_path")
    if result_name_path:
        reported_name = _get_path(result, result_name_path)
        add_check("reported_name", reported_name, parsed["name"], reported_name == parsed["name"])
    result_values_path = check.get("result_values_path")
    if result_values_path:
        reported_values = _get_path(result, result_values_path)
        add_check(
            "reported_values",
            reported_values,
            values,
            _numeric_lists_close(reported_values, values, float(check.get("abs_tol", 1e-9))),
        )
    result_count_path = check.get("result_count_path")
    if result_count_path:
        reported_count = _get_path(result, result_count_path)
        add_check("reported_count", reported_count, len(values), reported_count == len(values))

    score = sum(int(item["matched"]) for item in checks) / len(checks) if checks else 0.0
    return score, {"parsed_commands": parsed_commands, "checks": checks}


def _grade_trace_response(check: dict[str, Any], result: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    selector = check.get("selector", {})
    responses = [event.payload.get("response") for event in raw_trace.TRACE if _event_matches(selector, event)]
    observed: Any = responses[-1] if responses else None
    parser = check.get("parse", "str")
    try:
        if parser == "bool_on_off":
            parsed = str(observed).strip().upper() in {"1", "ON", "TRUE"} if observed is not None else None
        elif parser == "float":
            parsed = float(observed)
        elif parser == "int":
            parsed = int(str(observed).strip())
        elif parser == "csv_field":
            fields = str(observed).strip().split(str(check.get("delimiter", ",")))
            parsed = fields[int(check.get("field_index", 0))].strip()
        elif parser == "prefixed_csv":
            text = str(observed).strip()
            prefix = str(check.get("prefix", ""))
            if prefix and not text.startswith(prefix):
                parsed = None
            else:
                payload = text[len(prefix):].strip()
                parsed = [item.strip() for item in payload.split(str(check.get("delimiter", ","))) if item.strip()]
        elif parser == "regex_group":
            match = re.search(str(check["response_regex"]), str(observed))
            if match is None:
                parsed = None
            else:
                parsed = match.group(check.get("group", 1))
                cast = check.get("cast", "str")
                if cast == "float":
                    parsed = float(parsed)
                elif cast == "int":
                    parsed = int(parsed)
                elif cast == "bool_int":
                    parsed = bool(int(parsed))
        else:
            parsed = str(observed).strip() if observed is not None else None
    except (IndexError, TypeError, ValueError):
        parsed = None

    checks: list[dict[str, Any]] = []
    if "expected" in check:
        expected = check["expected"]
        matched = _match_expected(parsed, expected) if isinstance(expected, dict) else parsed == expected
        checks.append({"label": "expected", "actual": parsed, "expected": expected, "matched": matched})
    if check.get("result_path"):
        reported = _get_path(result, check["result_path"])
        result_match = check.get("result_match", "parsed")
        if result_match == "raw":
            accepted = [observed]
        elif result_match == "raw_or_parsed":
            accepted = [parsed, observed]
        else:
            accepted = [parsed]
        matched = any(_values_close(reported, value) for value in accepted)
        checks.append(
            {
                "label": "result",
                "actual": reported,
                "expected": accepted[0] if len(accepted) == 1 else accepted,
                "result_match": result_match,
                "matched": matched,
            }
        )
    score = sum(int(item["matched"]) for item in checks) / len(checks) if checks and responses else 0.0
    return score, {"responses": responses, "parsed": parsed, "checks": checks}


def _grade_result_threshold_decision(
    check: dict[str, Any], result: dict[str, Any]
) -> tuple[float, dict[str, Any]]:
    condition_results: list[dict[str, Any]] = []
    for condition in check.get("conditions", []):
        actual = _get_path(result, condition["path"])
        if "equals" in condition:
            error = None
            passed = actual == condition["equals"]
        elif "range" in condition:
            error = None
            try:
                low, high = condition["range"]
                passed = float(low) <= float(actual) <= float(high)
            except (TypeError, ValueError):
                passed = False
        elif "max" in condition:
            error = None
            try:
                passed = float(actual) <= float(condition["max"])
            except (TypeError, ValueError):
                passed = False
        elif "min" in condition:
            error = None
            try:
                passed = float(actual) >= float(condition["min"])
            except (TypeError, ValueError):
                passed = False
        else:
            try:
                error = abs(float(actual) - float(condition["target"]))
                passed = error <= float(condition["abs_tol"])
            except (KeyError, TypeError, ValueError):
                error = None
                passed = False
        condition_results.append({**condition, "actual": actual, "error": error, "passed": passed})
    condition_passed = bool(condition_results) and all(item["passed"] for item in condition_results)
    label_mode = "true_value" in check or "false_value" in check
    expected = (
        check.get("true_value") if condition_passed else check.get("false_value")
    ) if label_mode else condition_passed
    reported = _get_path(result, check["result_path"])
    matched = reported == expected if label_mode else isinstance(reported, bool) and reported == expected
    return (1.0 if matched else 0.0), {
        "reported": reported,
        "expected": expected,
        "conditions": condition_results,
    }


def _grade_result_endpoint_slope(
    check: dict[str, Any], result: dict[str, Any]
) -> tuple[float, dict[str, Any]]:
    xs = _get_path(result, check["x_path"])
    ys = _get_path(result, check["y_path"])
    reported = _get_path(result, check["slope_path"])
    derived: float | None = None
    matched = False
    if isinstance(xs, list) and isinstance(ys, list) and len(xs) == len(ys) and len(xs) >= 2:
        try:
            delta_x = float(xs[-1]) - float(xs[0])
            if delta_x != 0:
                derived = (float(ys[-1]) - float(ys[0])) / delta_x
                matched = _float_close(reported, derived, float(check.get("abs_tol", 1e-9)))
        except (TypeError, ValueError):
            pass
    return (1.0 if matched else 0.0), {
        "x_values": xs,
        "y_values": ys,
        "reported": reported,
        "derived": derived,
        "matched": matched,
    }


def _grade_result_mean_deviation_validation(
    check: dict[str, Any], result: dict[str, Any]
) -> tuple[float, dict[str, Any]]:
    values = _get_path(result, check["values_path"])
    reported_average = _get_path(result, check["average_path"])
    reported_deviation = _get_path(result, check["deviation_path"])
    reported_decision = _get_path(result, check["result_path"])
    derived_average: float | None = None
    derived_deviation: float | None = None
    expected_decision = False
    if isinstance(values, list) and len(values) == 2:
        try:
            numeric = [float(value) for value in values]
            derived_average = statistics.mean(numeric)
            derived_deviation = abs(numeric[1] - numeric[0]) / 2
            tolerance = float(check.get("abs_tol", 1e-9))
            expected_decision = _float_close(reported_average, derived_average, tolerance) and _float_close(
                reported_deviation, derived_deviation, tolerance
            )
        except (TypeError, ValueError):
            pass
    matched = isinstance(reported_decision, bool) and reported_decision == expected_decision
    return (1.0 if matched else 0.0), {
        "values": values,
        "reported_average": reported_average,
        "derived_average": derived_average,
        "reported_deviation": reported_deviation,
        "derived_deviation": derived_deviation,
        "reported_decision": reported_decision,
        "expected_decision": expected_decision,
        "matched": matched,
    }


def _grade_result_argmax_x(
    check: dict[str, Any], result: dict[str, Any]
) -> tuple[float, dict[str, Any]]:
    xs = _get_path(result, check["x_path"])
    ys = _get_path(result, check["y_path"])
    reported = _get_path(result, check["result_path"])
    expected: Any = None
    if isinstance(xs, list) and isinstance(ys, list) and xs and len(xs) == len(ys):
        try:
            expected = xs[max(range(len(ys)), key=lambda index: float(ys[index]))]
        except (TypeError, ValueError):
            expected = None
    matched = expected is not None and _float_close(reported, expected, float(check.get("abs_tol", 1e-9)))
    return (1.0 if matched else 0.0), {
        "x_values": xs,
        "y_values": ys,
        "reported": reported,
        "expected": expected,
        "matched": matched,
    }


def _grade_result_pairwise_max_abs_error(
    check: dict[str, Any], result: dict[str, Any]
) -> tuple[float, dict[str, Any]]:
    left = _get_path(result, check["left_path"])
    right = _get_path(result, check["right_path"])
    reported = _get_path(result, check["result_path"])
    if not isinstance(left, list) or not isinstance(right, list) or not left or len(left) != len(right):
        derived = None
        matched = False
    else:
        try:
            derived = max(abs(float(a) - float(b)) for a, b in zip(left, right))
            matched = _float_close(reported, derived, float(check.get("abs_tol", 1e-9)))
        except (TypeError, ValueError):
            derived = None
            matched = False
    return (1.0 if matched else 0.0), {
        "left": left,
        "right": right,
        "reported": reported,
        "derived": derived,
        "matched": matched,
    }


def _grade_result_pairwise_differences(
    check: dict[str, Any], result: dict[str, Any]
) -> tuple[float, dict[str, Any]]:
    left = _get_path(result, check["left_path"])
    right = _get_path(result, check["right_path"])
    reported = _get_path(result, check["result_path"])
    derived: list[float] = []
    if isinstance(left, list) and isinstance(right, list) and left and len(left) == len(right):
        try:
            derived = [float(b) - float(a) for a, b in zip(left, right)]
        except (TypeError, ValueError):
            derived = []
    matched = bool(derived) and _numeric_lists_close(
        reported, derived, float(check.get("abs_tol", 1e-9))
    )
    return (1.0 if matched else 0.0), {
        "left": left,
        "right": right,
        "reported": reported,
        "derived": derived,
        "matched": matched,
    }


def _grade_result_linear_fit(
    check: dict[str, Any], result: dict[str, Any]
) -> tuple[float, dict[str, Any]]:
    xs = _get_path(result, check["x_path"])
    ys = _get_path(result, check["y_path"])
    reported_slope = _get_path(result, check["slope_path"])
    reported_intercept = _get_path(result, check["intercept_path"])
    slope: float | None = None
    intercept: float | None = None
    slope_match = False
    intercept_match = False
    if isinstance(xs, list) and isinstance(ys, list) and len(xs) == len(ys) and len(xs) >= 2:
        try:
            numeric_xs = [float(value) for value in xs]
            numeric_ys = [float(value) for value in ys]
            mean_x = statistics.mean(numeric_xs)
            mean_y = statistics.mean(numeric_ys)
            denominator = sum((value - mean_x) ** 2 for value in numeric_xs)
            if denominator > 0:
                slope = sum(
                    (x_value - mean_x) * (y_value - mean_y)
                    for x_value, y_value in zip(numeric_xs, numeric_ys)
                ) / denominator
                intercept = mean_y - slope * mean_x
                tolerance = float(check.get("abs_tol", 1e-9))
                slope_match = _float_close(reported_slope, slope, tolerance)
                intercept_match = _float_close(reported_intercept, intercept, tolerance)
        except (TypeError, ValueError):
            pass
    score = (int(slope_match) + int(intercept_match)) / 2
    return score, {
        "x_values": xs,
        "y_values": ys,
        "reported_slope": reported_slope,
        "derived_slope": slope,
        "slope_matched": slope_match,
        "reported_intercept": reported_intercept,
        "derived_intercept": intercept,
        "intercept_matched": intercept_match,
    }


def _parse_ieee_block_payload(data: bytes) -> bytes:
    if len(data) < 3 or data[0:1] != b"#" or not bytes([data[1]]).isdigit():
        raise ValueError("response is not an IEEE definite-length block")
    digit_count = int(chr(data[1]))
    if digit_count <= 0 or len(data) < 2 + digit_count:
        raise ValueError("invalid IEEE block length header")
    length_bytes = data[2 : 2 + digit_count]
    if not length_bytes.isdigit():
        raise ValueError("IEEE block payload length is not decimal")
    payload_length = int(length_bytes.decode("ascii"))
    payload_start = 2 + digit_count
    payload_end = payload_start + payload_length
    if len(data) < payload_end:
        raise ValueError(f"truncated IEEE block: expected {payload_length} payload bytes")
    return data[payload_start:payload_end]


def _grade_numeric_assertions(
    check: dict[str, Any], result: dict[str, Any], values: list[float]
) -> tuple[float, dict[str, Any]]:
    assertions: list[dict[str, Any]] = check.get("assertions", [])
    assertion_results: list[dict[str, Any]] = []
    matched_count = 0
    for assertion in assertions:
        operation = assertion["aggregate"]
        derived: Any = list(values) if operation == "values" else _aggregate_numeric(values, operation)
        actual = _get_path(result, assertion["result_path"])
        comparison = assertion.get("compare", "close")
        if not values:
            expected = None
            matched = False
        elif comparison == "lt":
            expected = derived < float(assertion["threshold"]) if derived is not None else None
            matched = actual is expected
        elif comparison == "le":
            expected = derived <= float(assertion["threshold"]) if derived is not None else None
            matched = actual is expected
        elif operation == "values":
            expected = derived
            matched = _numeric_lists_close(actual, derived, float(assertion.get("abs_tol", 1e-9)))
        else:
            expected = derived
            matched = derived is not None and _float_close(actual, derived, float(assertion.get("abs_tol", 1e-9)))
        matched_count += int(matched)
        assertion_results.append(
            {
                "result_path": assertion["result_path"],
                "aggregate": operation,
                "actual": actual,
                "derived": derived,
                "expected": expected,
                "matched": matched,
            }
        )

    score = matched_count / len(assertions) if assertions else (1.0 if values else 0.0)
    return score, {"values": values, "assertions": assertion_results}


def _numeric_lists_close(actual: Any, expected: list[float], abs_tol: float) -> bool:
    if not isinstance(actual, list) or len(actual) != len(expected):
        return False
    return all(_float_close(left, right, abs_tol) for left, right in zip(actual, expected))


def _aggregate_numeric(values: list[float], operation: str) -> float | None:
    if operation == "count":
        return float(len(values))
    if not values:
        return None
    if operation == "mean":
        return float(statistics.mean(values))
    if operation == "sample_stdev":
        return float(statistics.stdev(values)) if len(values) >= 2 else None
    if operation == "population_stdev":
        return float(statistics.pstdev(values))
    if operation == "min":
        return min(values)
    if operation == "max":
        return max(values)
    if operation == "first":
        return values[0]
    if operation == "last":
        return values[-1]
    raise ValueError(f"Unsupported numeric aggregate: {operation}")


def _get_path(data: Any, path: str) -> Any:
    if path in {"", "$"}:
        return data
    current = data
    for part in path.lstrip("$.").split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _snapshot_gateway(gateway: Any) -> dict[str, Any]:
    snapshot = getattr(gateway, "snapshot_state", None)
    if callable(snapshot):
        try:
            state = snapshot()
            return state if isinstance(state, dict) else {"value": state}
        except Exception as exc:
            return {"snapshot_error": str(exc)}
    return {}
