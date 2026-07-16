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
CATEGORY_WEIGHTS = {
    "patch_application": 2.0,
    "build_and_load": 8.0,
    "bug_fix": 35.0,
    "regression": 20.0,
    "state_trace_behavior": 10.0,
    "trace_checkpoints": 10.0,
    "minefields": 15.0,
}


def prepare(instance: Path) -> Path:
    work = instance / ".work"
    if work.exists(): shutil.rmtree(work)
    shutil.copytree(instance / "repository", work / "repository")
    return work


def apply_patch(work: Path, patch: Path) -> None:
    from evaluator.unified_patch import apply_unified_patch
    repository = work / "repository"
    try:
        apply_unified_patch(repository, patch.resolve())
    except ValueError:
        # The strict matcher may have applied earlier files before discovering
        # a CRLF hunk. Restore the pristine snapshot before retrying.
        pristine = work.parent / "repository"
        if pristine != repository and pristine.exists():
            shutil.rmtree(repository)
            shutil.copytree(pristine, repository)
        # Isolate a temporary index so git's outer worktree cannot absorb
        # patches for snapshots that are not themselves repositories.
        subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
        subprocess.run(["git", "add", "-A"], cwd=repository, check=True)
        subprocess.run(["git", "apply", "--ignore-whitespace", "--ignore-space-change", "--whitespace=nowarn", str(patch.resolve())], cwd=repository, check=True)
        shutil.rmtree(repository / ".git", ignore_errors=True)


def run_layer(instance: Path, work: Path, layer: str) -> dict:
    metadata = json.loads((instance / "instance.json").read_text())
    if metadata.get("language") == "cpp":
        trace = work / f"{layer}.trace.json"
        env = {**os.environ, "IAB_REPOSITORY": str(work / "repository"), "IAB_TRACE_PATH": str(trace)}
        proc = subprocess.run(["bash", str(instance / "run_cpp_tests.sh"), layer], cwd=instance, env=env, text=True, capture_output=True)
        marker = next((line for line in reversed(proc.stdout.splitlines()) if line.startswith("IAB_CPP_RESULTS=")), "")
        if marker:
            payload = json.loads(marker.removeprefix("IAB_CPP_RESULTS="))
        else:
            payload = next((json.loads(line) for line in reversed(proc.stdout.splitlines()) if line.startswith("{")), {"tests": []})
        return {"passed": proc.returncode == 0, "returncode": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:], "trace": str(trace) if trace.exists() else None, "tests": payload.get("tests", [])}
    trace = work / f"{layer}.trace.json"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(work / "repository"), str(instance), str(ROOT)]), "IAB_TRACE_PATH": str(trace), "IAB_REPOSITORY": str(work / "repository")}
    test = instance / "tests" / f"test_{layer}.py"
    proc = subprocess.run([sys.executable, str(ROOT / "evaluator" / "test_executor.py"), str(test), "--json"], cwd=work, env=env, text=True, capture_output=True)
    marker = next((line for line in reversed(proc.stdout.splitlines()) if line.startswith("IAB_TEST_RESULTS=")), "")
    tests = json.loads(marker.removeprefix("IAB_TEST_RESULTS="))["tests"] if marker else []
    return {"passed": proc.returncode == 0, "returncode": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:], "trace": str(trace) if trace.exists() else None, "tests": tests}


def configured_layers(instance: Path) -> tuple[str, ...]:
    manifest = instance / "evaluation_manifest.json"
    if not manifest.exists(): return LAYERS
    payload = json.loads(manifest.read_text())
    if payload.get("schema_version") not in {1, 2}: raise ValueError("unsupported evaluation manifest")
    layers = tuple(payload.get("layers", payload.get("strict_layers", [])))
    if not layers or "fail_to_pass" not in layers: raise ValueError("evaluation manifest must include fail_to_pass")
    return layers


def differential(instance: Path, work: Path) -> dict:
    actual_path, expected_path = work / "state_trace.trace.json", instance / "expected" / "gold_trace.json"
    expected = json.loads(expected_path.read_text())
    if not actual_path.exists(): return {"passed": False, "errors": ["state trace was not produced"], "matched": 0, "total": len(expected)}
    from evaluator.trace_compare import compare_trace_progress
    matched, errors = compare_trace_progress(json.loads(actual_path.read_text()), expected)
    return {"passed": matched == len(expected), "errors": errors, "matched": matched, "total": len(expected)}


def fraction(tests: list[dict]) -> float:
    return sum(bool(test.get("passed")) for test in tests) / len(tests) if tests else 0.0


def scored_report(mode: str, layers: dict, passed: bool, *, infrastructure_error: bool = False, patch_applied: bool = True) -> dict:
    from evaluator.confidence import calculate_confidence
    trace = layers.get("gold_differential", {})
    total = trace.get("total", 0)
    categories = {
        "patch_application": {"weight": 2.0, "fraction": 1.0 if patch_applied else 0.0},
        "build_and_load": {"weight": 8.0, "fraction": fraction(layers.get("build_and_load", {}).get("tests", [])) if "build_and_load" in layers else 1.0},
        "bug_fix": {"weight": 35.0, "fraction": fraction(layers.get("fail_to_pass", {}).get("tests", []))},
        "regression": {"weight": 20.0, "fraction": fraction(layers.get("regression", {}).get("tests", []))},
        "state_trace_behavior": {"weight": 10.0, "fraction": fraction(layers.get("state_trace", {}).get("tests", []))},
        "trace_checkpoints": {"weight": 10.0, "fraction": trace.get("matched", 0) / total if total else 0.0},
        "minefields": {"weight": 15.0, "fraction": fraction(layers.get("minefields", {}).get("tests", []))},
    }
    if not patch_applied:
        for value in categories.values(): value["fraction"] = 0.0
    for value in categories.values(): value["earned"] = round(value["weight"] * value["fraction"], 4)
    tests = [{**test, "layer": layer} for layer, result in layers.items() for test in result.get("tests", [])]
    failure_kind = None if passed else ("infrastructure_error" if infrastructure_error else "test")
    return {
        "schema_version": 2, "strict_pass": passed, "passed": passed,
        "evaluation_score": round(sum(value["earned"] for value in categories.values()), 4),
        "score": round(sum(value["earned"] for value in categories.values()), 4),
        "categories": categories, "tests": tests,
        "trace_checkpoints": {"matched": trace.get("matched", 0), "total": total, "errors": trace.get("errors", [])},
        "failure_kind": failure_kind, "mode": mode, "layers": layers,
        "confidence": calculate_confidence(layers, infrastructure_error=infrastructure_error),
    }


def write_report(instance: Path, mode: str, layers: dict, passed: bool, *, failure_kind: str | None = None, infrastructure_error: bool = False, patch_applied: bool = True) -> None:
    identifier = json.loads((instance / "instance.json").read_text())["instance_id"]
    report = scored_report(mode, layers, passed, infrastructure_error=infrastructure_error, patch_applied=patch_applied)
    report["instance_id"] = identifier
    if failure_kind is not None: report["failure_kind"] = failure_kind
    target = instance / ".work" / "evaluation_report.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"instance_id": identifier, "mode": mode, "passed": passed, "strict_pass": passed, "score": report["score"], "report": str(target)}))


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
        work = prepare(instance)
        try:
            apply_patch(work, args.patch)
        except Exception as exc:
            write_report(instance, args.mode, {"patch_application": {"passed": False, "returncode": 1, "tests": [], "stderr": str(exc)}}, False, failure_kind="patch_apply", infrastructure_error=True, patch_applied=False)
            return 1
    if args.mode == "pre-fix":
        result = run_layer(instance, work, "fail_to_pass")
        confirmed = not result["passed"]
        write_report(instance, args.mode, {"fail_to_pass": result}, confirmed)
        return 0 if confirmed else 1
    layers = {layer: run_layer(instance, work, layer) for layer in configured_layers(instance)}
    layers["gold_differential"] = differential(instance, work)
    passed = all(result["passed"] for result in layers.values())
    write_report(instance, args.mode, layers, passed)
    return 0 if passed else 1


if __name__ == "__main__": raise SystemExit(main())
