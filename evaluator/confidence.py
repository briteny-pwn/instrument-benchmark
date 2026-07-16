"""Conservative evidence-confidence calculation for evaluation reports.

Confidence is deliberately separate from the model's evaluation score.  A
patch can score well on a tiny test set while still having weak evidence.
"""

from __future__ import annotations

from typing import Any


REQUIRED_EVIDENCE = ("fail_to_pass", "regression", "state_trace", "minefields", "gold_differential")


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def calculate_confidence(layers: dict[str, Any], *, infrastructure_error: bool = False) -> dict[str, Any]:
    present = sum(name in layers for name in REQUIRED_EVIDENCE)
    coverage = present / len(REQUIRED_EVIDENCE)
    test_counts = [len(result.get("tests", [])) for name, result in layers.items() if name != "gold_differential"]
    total_tests = sum(test_counts)
    assertion_evidence = _clip(total_tests / 10.0)
    trace = layers.get("gold_differential", {})
    trace_total = int(trace.get("total", 0) or 0)
    trace_match = int(trace.get("matched", 0) or 0)
    trace_evidence = _clip(trace_match / trace_total) if trace_total else 0.0
    executed = [result for name, result in layers.items() if name != "gold_differential"]
    reproducibility = sum("returncode" in result for result in executed) / len(executed) if executed else 0.0
    infrastructure = 0.0 if infrastructure_error else 1.0
    score = round(100.0 * (0.25 * coverage + 0.25 * assertion_evidence + 0.20 * trace_evidence + 0.20 * reproducibility + 0.10 * infrastructure), 2)
    level = "high" if score >= 85 else "medium" if score >= 60 else "low"
    return {
        "score": score,
        "level": level,
        "factors": {
            "layer_coverage": round(coverage, 4),
            "assertion_evidence": round(assertion_evidence, 4),
            "trace_evidence": round(trace_evidence, 4),
            "reproducibility": round(reproducibility, 4),
            "infrastructure": infrastructure,
        },
        "basis": {"layers_observed": present, "layers_required": len(REQUIRED_EVIDENCE), "assertions_observed": total_tests, "trace_checkpoints_matched": trace_match, "trace_checkpoints_total": trace_total},
    }
