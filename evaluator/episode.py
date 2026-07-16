"""Scenario-driven evaluation for scientific instrument integration episodes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def load_manifest(episode: Path) -> dict[str, Any]:
    return json.loads((episode / "episode.json").read_text())


def run_episode(episode: Path) -> dict[str, Any]:
    manifest = load_manifest(episode)
    proc = subprocess.run([sys.executable, "harness.py"], cwd=episode, text=True, capture_output=True)
    marker = next((line for line in proc.stdout.splitlines() if line.startswith("IAB_EPISODE_RESULTS=")), "")
    result = json.loads(marker.removeprefix("IAB_EPISODE_RESULTS=")) if marker else {"scenarios": []}
    scenarios = {item["id"]: item for item in result.get("scenarios", [])}
    total_weight = sum(float(item["weight"]) for item in manifest["scenarios"])
    earned = sum(float(item["weight"]) for item in manifest["scenarios"] if scenarios.get(item["id"], {}).get("passed"))
    score = round(100 * earned / total_weight, 2) if total_weight else 0.0
    strict = all(scenarios.get(item["id"], {}).get("passed") for item in manifest["scenarios"])
    return {"schema_version": 1, "episode_id": manifest["episode_id"], "strict_pass": strict, "score": score, "scenarios": result.get("scenarios", []), "stderr": proc.stderr[-4000:], "returncode": proc.returncode}
