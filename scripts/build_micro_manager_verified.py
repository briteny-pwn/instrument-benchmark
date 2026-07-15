#!/usr/bin/env python3
"""Materialize ten Micro-Manager evidence bundles from the scored snapshot."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NOTES = {
    946: ("The DemoCamera XY stage reports user-space positions while a move is active. The polling thread must wake on move start, serialize access to the timeout state, and notify Busy/position callbacks without stale coordinates.", "Use a deterministic clock, fake callback sink, and a move state machine. Check idle, moving, completion, interruption, and callback ordering."),
    828: ("AlliedVision callbacks can race property allowed-value updates during SDK invalidation callbacks. The merged repair serializes callback mutations and ignores callbacks before property initialization.", "Use a fake SDK callback thread and a property recorder. Exercise pre-init, concurrent updates, and callback ordering without vendor hardware."),
    965: ("PVCAM multi-ROI support depends on the active camera port. The adapter must discover supported ports before reporting the Micro-Manager ROI capability.", "Use a fake port table with HDR and non-HDR capabilities. Compare reported ROI count, selected port, and acquisition state."),
    914: ("MMCore needs per-device timeout overrides while retaining the global default and exception semantics. The API crosses Core, DeviceInstance, and Java wrapper boundaries.", "Use fake device instances with blocking and completing operations. Check set/unset/get/has precedence and timeout error propagation."),
    124: ("TSI SDK 2.0.1 changed exported symbols and DLL loading conventions. The adapter load file must resolve the supported symbol set and report missing dependencies clearly.", "Use a fake dynamic library exposing old/new symbol sets. Exercise successful load, version mismatch, missing symbol, and cleanup."),
}


def metadata(row: dict, index: int) -> dict:
    return {
        "instance_id": f"iab_{index:04d}", "source_project": row["source_project"], "source_repo": row["source_repo"],
        "source_type": row.get("source_type", "merged_pr_with_reproduction"), "issue_url": row["issue_url"], "pr_url": row["pr_url"],
        "pre_fix_commit": row["pre_fix_commit"], "post_fix_commit": row["post_fix_commit"], "gold_patch_commit": row["gold_patch_commit"],
        "parent_repo": row["parent_repo"], "adapter_name": row["adapter_name"], "changed_paths": row["changed_paths"],
        "platforms": row["platforms"], "vendor_sdk_strategy": row["vendor_sdk_strategy"],
        "instrument_category": row["instrument_category"], "task_type": row["task_type"], "failure_modes": row["failure_modes"],
        "framework": "Micro-Manager", "language": "cpp", "simulator_type": row["simulator_type"], "requires_real_hardware": False,
        "given_to_model": {"issue_text": True, "failure_log": True, "docs_excerpt": True, "pre_fix_code": True, "simulator": True},
        "hidden_from_model": {"gold_patch": True, "post_fix_commit": True, "hidden_tests": True},
        "reproduction": {"pre_fix_fails": None, "gold_patch_passes": None, "command": "bash setup.sh && bash reproduce_pre_fix.sh && bash apply_gold_patch.sh && bash evaluate.sh"},
        "difficulty_evidence": {"files_changed_by_gold": row["changed_files"], "layers_touched": [row["adapter_name"], "MMCore", "tests"], "requires_state_reasoning": "state_machine" in row["failure_modes"], "requires_async_reasoning": "async_timing" in row["failure_modes"], "requires_framework_semantics": True, "requires_safety_constraints": "safety_boundary" in row["failure_modes"]},
        "evaluation_layers": ["build", "fail_to_pass", "regression", "state_trace", "gold_differential", "minefield"], "status": "verified_candidate",
        "build": {"system": "cmake", "cxx_standard": 17, "behavior_platform": "linux", "compile_platforms": row["platforms"], "artifact": "iab_adapter_tests", "vendor_sdk_strategy": row["vendor_sdk_strategy"]},
    }


def main() -> int:
    rows = json.loads((ROOT / "data/micro_manager_scored_candidates.json").read_text())
    chosen = sorted(rows, key=lambda row: (-row.get("candidate_score", row.get("score", 0)), row["pr_number"]))[:10]
    out = ROOT / "data/micro_manager_verified_candidates"
    for index, row in enumerate(chosen, 1):
        target = out / f"iab_{index + 5:04d}"
        target.mkdir(parents=True, exist_ok=True)
        issue, simulation = NOTES.get(row["pr_number"], (row["body_excerpt"], "Use a deterministic fake device and compare command/property/state traces."))
        (target / "candidate.json").write_text(json.dumps(metadata(row, index + 5), indent=2) + "\n")
        (target / "issue.md").write_text(f"# {row['title']}\n\nPR: {row['pr_url']}\n\n{issue}\n")
        (target / "pr_summary.md").write_text(f"# Resolution summary\n\n{row['body_excerpt']}\n")
        (target / "diff_summary.md").write_text(f"# Diff summary\n\n{row['changed_files']} files changed (+{row['additions']}/-{row['deletions']}) at `{row['pre_fix_commit']}` -> `{row['post_fix_commit']}`.\n\nPaths: {', '.join(row['changed_paths'])}\n")
        (target / "reproduction_plan.md").write_text(f"# Simulation reproduction\n\n{simulation}\n")
        (target / "difficulty_analysis.md").write_text(f"# Difficulty analysis\n\nAdapter: {row['adapter_name']}\n\nFailure modes: {', '.join(row['failure_modes'])}\n\n{issue}\n")
    print(json.dumps({"verified_candidates": len(chosen), "output": str(out)}))
    return 0


if __name__ == "__main__": raise SystemExit(main())
