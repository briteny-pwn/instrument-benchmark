"""Scenario-driven evaluation for scientific instrument integration episodes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def load_manifest(episode: Path) -> dict[str, Any]:
    return json.loads((episode / "episode.json").read_text())


def ordered_subsequence(events: list[str], required: list[str]) -> bool:
    cursor = 0
    for event in events:
        if cursor < len(required) and event == required[cursor]:
            cursor += 1
    return cursor == len(required)


def run_episode(episode: Path, patch: Path | None = None, *, repository: Path | None = None) -> dict[str, Any]:
    episode = episode.resolve()
    if repository is not None: repository = repository.resolve()
    manifest = load_manifest(episode)
    work = episode / ".work"
    if work.exists(): shutil.rmtree(work)
    shutil.copytree(repository or episode / "repository", work / "repository")
    if patch is not None:
        from evaluator.run_instance import apply_patch
        try:
            apply_patch(work, patch)
        except Exception as exc:
            return {"schema_version": 1, "episode_id": manifest["episode_id"], "strict_pass": False, "score": 0.0, "scenarios": [], "failure_kind": "patch_apply", "error": str(exc)}
    env = {**os.environ, "IAB_EPISODE_REPOSITORY": str(work / "repository")}
    proc = subprocess.run([sys.executable, "harness.py"], cwd=episode, env=env, text=True, capture_output=True)
    marker = next((line for line in proc.stdout.splitlines() if line.startswith("IAB_EPISODE_RESULTS=")), "")
    result = json.loads(marker.removeprefix("IAB_EPISODE_RESULTS=")) if marker else {"scenarios": []}
    scenarios = {item["id"]: item for item in result.get("scenarios", [])}
    for spec in manifest["scenarios"]:
        observed = scenarios.get(spec["id"], {})
        observed["passed"] = bool(observed.get("passed")) and ordered_subsequence(observed.get("events", []), spec["required_events"])
    total_weight = sum(float(item["weight"]) for item in manifest["scenarios"])
    earned = sum(float(item["weight"]) for item in manifest["scenarios"] if scenarios.get(item["id"], {}).get("passed"))
    score = round(100 * earned / total_weight, 2) if total_weight else 0.0
    strict = all(scenarios.get(item["id"], {}).get("passed") for item in manifest["scenarios"])
    return {"schema_version": 1, "episode_id": manifest["episode_id"], "strict_pass": strict, "score": score, "scenarios": result.get("scenarios", []), "stderr": proc.stderr[-4000:], "returncode": proc.returncode}
