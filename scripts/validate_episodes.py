#!/usr/bin/env python3
"""Validate scenario-driven integration episodes and execute their contracts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluator.episode import load_manifest, run_episode


def main() -> int:
    failures = []
    reports = {}
    for episode in sorted((ROOT / "episodes").glob("iep_*")):
        manifest = load_manifest(episode)
        if len(manifest.get("scenarios", [])) < 3: failures.append(f"{episode.name}: fewer than three scenarios")
        if manifest.get("provenance", {}).get("fixture_kind") != "contract_projection": failures.append(f"{episode.name}: missing fixture transparency")
        pre = run_episode(episode)
        gold = run_episode(episode, repository=episode / "gold")
        reports[episode.name] = {"pre_fix": pre, "gold": gold}
        if pre["strict_pass"]: failures.append(f"{episode.name}: pre-fix unexpectedly passes")
        if not gold["strict_pass"] or gold["score"] != 100.0: failures.append(f"{episode.name}: gold contract failed")
    output = {"schema_version": 1, "passed": not failures, "episodes": reports, "failures": failures}
    (ROOT / "reports/integration_episode_validation.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({"passed": output["passed"], "episodes": len(reports), "failures": failures}))
    return 0 if output["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
