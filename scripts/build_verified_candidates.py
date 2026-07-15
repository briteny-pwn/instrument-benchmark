#!/usr/bin/env python3
"""Materialize the five reviewed evidence bundles from structured provenance."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NOTES = {
    1243: {
        "issue": "A previous per-Component timeout change removed the effective class-wide EpicsSignal default. Users need both class defaults and per-device overrides, with a regression test for the standard set_defaults path.",
        "gold": "Restores signal default timeout handling, adds Device-level connection timeout defaults/overrides, and tests the precedence and timeout paths.",
        "difficulty": "Timeout configuration crosses Component construction, Device traversal, and EPICS signal connection lifecycle. The repair must preserve override precedence and raise on genuinely disconnected children.",
        "sim": "Use mocked connected/disconnected child signals and a deterministic clock. Exercise class default, instance override, immediate connection, and timeout paths.",
        "oracle": "Upstream tests plus observed timeout propagation, exception timing, and child connection-call trace.",
    },
    1257: {
        "issue": "EpicsSignalNoValidation documents separate read/write PV support but rejects write_pv during construction, forwarding it to Signal where it raises TypeError.",
        "gold": "Aligns EpicsSignalNoValidation initialization with EpicsSignalBase and adds coverage for a distinct write PV.",
        "difficulty": "The bug is a framework constructor-semantics mismatch: keyword ownership and MRO forwarding must be correct without reintroducing connection validation.",
        "sim": "Mock read and write PV objects with independent values and record constructor/get/put calls.",
        "oracle": "Construction succeeds, reads use the read PV, writes use the write PV, and the no-validation behavior is retained.",
    },
    1219: {
        "issue": "Device.trigger ignores the trigger_value declared on a Component and always writes 1, contradicting the documented component contract.",
        "gold": "Carries the Component trigger_value into the trigger signal set call and adds a non-default-value regression test.",
        "difficulty": "This is control-framework state semantics, not generic arithmetic: the configured command value can encode a device-specific trigger transition.",
        "sim": "A stateful fake detector accepts only its configured trigger token and records idle-to-acquiring-to-complete transitions.",
        "oracle": "The trace contains the configured token, exactly one trigger transition, completion is awaited, and default trigger behavior still works.",
    },
    1207: {
        "issue": "EpicsSignal.set fails when writing a short array to an EPICS PV whose readback returns the full native array; shape mismatch reaches numpy comparison and produces FailedStatus.",
        "gold": "Compares the meaningful written prefix for array PV readback while preserving scalar and equal-shape comparisons, with regression tests.",
        "difficulty": "The oracle depends on EPICS Channel Access readback semantics, asynchronous set completion, array shape, and stale trailing buffer values.",
        "sim": "A fake array PV keeps a fixed-capacity buffer, updates only the written prefix, and returns full readback with controllable stale tail data.",
        "oracle": "Set completes when the written prefix matches, fails on a changed prefix, ignores only the irrelevant tail, and preserves scalar/equal-array behavior.",
    },
    440: {
        "issue": "Instrument.open_tcpip always forwards auth=None into concrete instrument constructors. Most drivers accept only filelike, so Ethernet-to-serial access fails with an unexpected keyword error.",
        "gold": "Forwards auth only when explicitly supplied, normalizes the Yokogawa constructor, and adds mocked TCP/IP regression tests.",
        "difficulty": "Connection factory semantics span socket setup, communicator wrapping, heterogeneous driver constructors, optional authentication, and cleanup after construction failure.",
        "sim": "Patch socket.create_connection with a fake socket and use unauthenticated/authenticated driver classes that record constructor and close calls.",
        "oracle": "Default access constructs legacy drivers without auth, explicit auth reaches capable drivers, incompatible explicit auth raises, and sockets are not leaked.",
    },
}


def metadata(row: dict, index: int) -> dict:
    modes = row["failure_modes"]
    return {
        "instance_id": f"iab_{index:04d}", "source_project": row["source_project"], "source_repo": row["source_repo"],
        "source_type": "resolved_issue_plus_pr", "issue_url": row["issue_url"], "pr_url": row["pr_url"],
        "pre_fix_commit": row["pre_fix_commit"], "post_fix_commit": row["post_fix_commit"], "gold_patch_commit": row["gold_patch_commit"],
        "instrument_category": "scientific_control" if row["source_project"] == "ophyd" else "laboratory_instrument",
        "task_type": row["task_type"], "failure_modes": modes, "framework": row["source_project"], "language": "python",
        "simulator_type": row["simulator_type"], "requires_real_hardware": False,
        "given_to_model": {"issue_text": True, "failure_log": True, "docs_excerpt": True, "pre_fix_code": True, "simulator": True},
        "hidden_from_model": {"gold_patch": True, "post_fix_commit": True, "hidden_tests": True},
        "reproduction": {"pre_fix_fails": None, "gold_patch_passes": None, "command": ""},
        "difficulty_evidence": {"files_changed_by_gold": row["changed_files"], "layers_touched": ["driver", "framework", "tests"], "requires_state_reasoning": "state_machine" in modes or "stale_data" in modes, "requires_async_reasoning": "timeout" in modes or "stale_data" in modes, "requires_framework_semantics": True, "requires_safety_constraints": "safety_boundary" in modes},
        "evaluation_layers": ["fail_to_pass", "regression", "state_trace", "gold_differential", "minefield"], "status": "verified_candidate",
    }


def main() -> int:
    rows = json.loads((ROOT / "data/reviewed_candidates.json").read_text())
    for index, row in enumerate(rows, 1):
        note, target = NOTES[row["pr_number"]], ROOT / "data/verified_candidates" / f"iab_{index:04d}"
        target.mkdir(parents=True, exist_ok=True)
        (target / "candidate.json").write_text(json.dumps(metadata(row, index), indent=2) + "\n")
        (target / "issue.md").write_text(f"# {row['issue_title']}\n\nSource: {row['issue_url']}\n\n{note['issue']}\n")
        (target / "pr_summary.md").write_text(f"# Resolution summary\n\nSource: {row['pr_url']}\n\n{note['gold']}\n")
        (target / "diff_summary.md").write_text(f"# Diff summary\n\nUpstream changed {row['changed_files']} files (+{row['additions']}/-{row['deletions']}) between `{row['pre_fix_commit']}` and `{row['post_fix_commit']}`.\n\n{note['gold']}\n")
        (target / "reproduction_plan.md").write_text(f"# Simulation reproduction\n\n{note['sim']}\n\nEvaluation oracle: {note['oracle']}\n")
        (target / "difficulty_analysis.md").write_text(
            "# Difficulty analysis\n\n"
            f"1. **Instrument access:** {note['issue']}\n"
            f"2. **Why this is not a generic software bug:** {note['difficulty']}\n"
            f"3. **Instrument/framework:** {row['domain']} through {row['source_project']}.\n"
            f"4. **Gold behavior:** {note['gold']}\n"
            f"5. **Difficulty source:** {', '.join(row['failure_modes'])}; {note['difficulty']}\n"
            f"6. **Phase-1 simulation:** {note['sim']}\n"
            f"7. **Evaluation oracle:** {note['oracle']}\n"
        )
    print(json.dumps({"verified_candidates": len(rows), "output": "data/verified_candidates"}))
    return 0


if __name__ == "__main__": raise SystemExit(main())
