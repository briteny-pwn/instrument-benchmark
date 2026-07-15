#!/usr/bin/env python3
"""Prepare, patch, and evaluate one IAB-Sim repair instance."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LAYERS = ("fail_to_pass", "regression", "state_trace", "minefields")


def prepare(instance: Path) -> Path:
    work = instance / ".work"
    if work.exists(): shutil.rmtree(work)
    shutil.copytree(instance / "repository", work / "repository")
    return work


def apply_patch(work: Path, patch: Path) -> None:
    from evaluator.unified_patch import apply_unified_patch
    apply_unified_patch(work / "repository", patch.resolve())


def run_layer(instance: Path, work: Path, layer: str) -> dict:
    trace = work / f"{layer}.trace.json"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(work / "repository"), str(instance), str(ROOT)]), "IAB_TRACE_PATH": str(trace), "IAB_REPOSITORY": str(work / "repository")}
    test = instance / "tests" / f"test_{layer}.py"
    proc = subprocess.run([sys.executable, str(ROOT / "evaluator" / "test_executor.py"), str(test)], cwd=work, env=env, text=True, capture_output=True)
    return {"passed": proc.returncode == 0, "returncode": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:], "trace": str(trace) if trace.exists() else None}


def differential(instance: Path, work: Path) -> dict:
    actual_path, expected_path = work / "state_trace.trace.json", instance / "expected" / "gold_trace.json"
    if not actual_path.exists(): return {"passed": False, "errors": ["state trace was not produced"]}
    from evaluator.trace_compare import compare_traces
    passed, errors = compare_traces(json.loads(actual_path.read_text()), json.loads(expected_path.read_text()))
    return {"passed": passed, "errors": errors}


def write_report(instance: Path, mode: str, layers: dict, passed: bool) -> None:
    identifier = json.loads((instance / "instance.json").read_text())["instance_id"]
    report = {"schema_version": 1, "instance_id": identifier, "mode": mode, "passed": passed, "layers": layers}
    target = instance / ".work" / "evaluation_report.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"instance_id": identifier, "mode": mode, "passed": passed, "report": str(target)}))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("instance")
    parser.add_argument("--mode", choices=("setup", "pre-fix", "apply-gold", "evaluate"), required=True)
    parser.add_argument("--patch", type=Path)
    args = parser.parse_args()
    instance = Path(args.instance).resolve()
    identifier = json.loads((instance / "instance.json").read_text())["instance_id"]
    work = instance / ".work"
    if args.mode == "setup":
        prepare(instance); print(json.dumps({"instance_id": identifier, "prepared": True})); return 0
    if not work.exists(): work = prepare(instance)
    if args.mode == "apply-gold":
        apply_patch(work, instance / "patches" / "gold.patch"); print(json.dumps({"instance_id": identifier, "gold_patch_applied": True})); return 0
    if args.patch:
        work = prepare(instance); apply_patch(work, args.patch)
    if args.mode == "pre-fix":
        result = run_layer(instance, work, "fail_to_pass")
        confirmed = not result["passed"]
        write_report(instance, args.mode, {"fail_to_pass": result}, confirmed)
        return 0 if confirmed else 1
    layers = {layer: run_layer(instance, work, layer) for layer in LAYERS}
    layers["gold_differential"] = differential(instance, work)
    passed = all(result["passed"] for result in layers.values())
    write_report(instance, args.mode, layers, passed)
    return 0 if passed else 1


if __name__ == "__main__": raise SystemExit(main())
