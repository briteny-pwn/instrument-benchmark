"""Deterministic candidate scoring from evidence flags."""

from __future__ import annotations

from typing import Any


WEIGHTS = {
    "has_issue": 5, "has_merged_pr": 5, "issue_pr_linked": 5, "has_discussion_or_log": 5,
    "touches_driver_adapter": 8, "real_instrument": 5, "framework_semantics": 5, "acquisition_or_state": 2,
    "multiple_files": 5, "state_async_timeout": 5, "version_compatibility": 4, "metadata_or_stale": 4,
    "framework_lifecycle": 4, "recovery_or_cleanup": 3, "mockable": 10, "trace_replayable": 5,
    "stateful_simulatable": 5, "no_real_hardware": 5, "upstream_tests": 4,
    "fail_to_pass_writable": 3, "regression_writable": 3,
}


def score_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence = candidate.get("evidence", {})
    breakdown = {name: weight if evidence.get(name) else 0 for name, weight in WEIGHTS.items()}
    score = sum(breakdown.values())
    grade = "verified_candidate" if score >= 80 else "candidate" if score >= 65 else "reserve" if score >= 50 else "drop"
    return {**candidate, "score": score, "score_breakdown": breakdown, "grade": grade}


def hard_filter_reasons(candidate: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    evidence = candidate.get("evidence", {})
    for key, label in {
        "has_merged_pr": "missing merged PR", "touches_driver_adapter": "not an integration change",
        "real_instrument": "no concrete instrument/device", "no_real_hardware": "requires real hardware",
    }.items():
        if not evidence.get(key): reasons.append(label)
    if not candidate.get("pre_fix_commit") or not candidate.get("post_fix_commit"):
        reasons.append("missing pre/post fix commit")
    if candidate.get("change_kind") in {"docs", "formatting", "ci", "dependency_only", "import_only"}:
        reasons.append(f"excluded change kind: {candidate['change_kind']}")
    if candidate.get("requires_real_hardware") is True:
        reasons.append("requires real hardware")
    if candidate.get("uses_private_sdk") is True:
        reasons.append("uses private SDK or manual")
    return reasons
