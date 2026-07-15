#!/usr/bin/env python3
"""End-to-end acceptance gate for the phase-1 plan."""

from __future__ import annotations

import json
import hashlib
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"^[0-9a-f]{40}$")
TASK_TYPES = {"real_bug_repair", "version_compatibility", "framework_semantic_integration", "multi_device_integration", "safety_critical_integration"}
FAILURE_MODES = {"state_machine", "async_timing", "timeout", "stale_data", "firmware_version_skew", "framework_semantic_mismatch", "resource_conflict", "metadata_mismatch", "device_initialization", "error_recovery", "safety_boundary", "multi_device_sync"}
VERIFIED_FILES = {"candidate.json", "issue.md", "pr_summary.md", "diff_summary.md", "reproduction_plan.md", "difficulty_analysis.md"}
INSTANCE_FILES = {"instance.json", "problem.md", "Dockerfile", "setup.sh", "reproduce_pre_fix.sh", "apply_gold_patch.sh", "evaluate.sh", "repository", "simulator", "tests", "patches", "expected"}


def check_metadata(meta: dict, expected_status: str | None = None) -> list[str]:
    errors = []
    if not re.fullmatch(r"iab_\d{4}", meta.get("instance_id", "")): errors.append("invalid instance_id")
    if meta.get("source_type") != "resolved_issue_plus_pr": errors.append("invalid source_type")
    if not meta.get("issue_url", "").startswith("https://github.com/"): errors.append("missing issue URL")
    if not meta.get("pr_url", "").startswith("https://github.com/"): errors.append("missing PR URL")
    for key in ("pre_fix_commit", "post_fix_commit", "gold_patch_commit"):
        if not SHA.fullmatch(meta.get(key, "")): errors.append(f"invalid {key}")
    if meta.get("task_type") not in TASK_TYPES: errors.append("invalid task_type")
    if not meta.get("failure_modes") or not set(meta["failure_modes"]) <= FAILURE_MODES: errors.append("invalid failure_modes")
    if meta.get("requires_real_hardware") is not False: errors.append("hardware dependency")
    if "protocol_to_sdk_basic" in json.dumps(meta): errors.append("excluded Level 1 task type")
    if expected_status and meta.get("status") != expected_status: errors.append(f"status is not {expected_status}")
    return errors


def command(script: Path, *args: str) -> dict:
    proc = subprocess.run(["bash", str(script), *args], cwd=ROOT, text=True, capture_output=True)
    return {"passed": proc.returncode == 0, "returncode": proc.returncode, "stdout": proc.stdout[-3000:], "stderr": proc.stderr[-3000:]}


def validate_source_snapshot(directory: Path) -> list[str]:
    errors, repository = [], directory / "repository"
    manifest = json.loads((repository / "source_manifest.json").read_text())
    metadata = json.loads((directory / "instance.json").read_text())
    if manifest.get("commit") != metadata.get("pre_fix_commit"): errors.append("source manifest commit differs from pre-fix commit")
    patch_text = (directory / "patches/gold.patch").read_text()
    for relative, expected in manifest.get("git_blobs", {}).items():
        data = (repository / relative).read_bytes()
        actual = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        if actual != expected: errors.append(f"upstream blob mismatch: {relative}")
        if f"index {expected[:7]}" not in patch_text and f"index {expected[:9]}" not in patch_text:
            errors.append(f"gold diff does not start from blob: {relative}")
    if set(manifest.get("files", [])) != set(manifest.get("git_blobs", {})): errors.append("source manifest file/blob mismatch")
    return errors


def validate_model_boundary(directory: Path) -> list[str]:
    sys.path.insert(0, str(ROOT))
    from evaluator.model_bundle import build_model_bundle
    metadata = json.loads((directory / "instance.json").read_text())
    with TemporaryDirectory() as tmp:
        bundle = build_model_bundle(directory, Path(tmp) / "bundle")
        relative_files = {path.relative_to(bundle).as_posix() for path in bundle.rglob("*") if path.is_file()}
        if any(path.startswith(("tests/", "patches/", "expected/")) or path == "instance.json" or path.endswith("source_manifest.json") for path in relative_files):
            return ["hidden evaluation material entered model bundle"]
        visible_text = "\n".join(path.read_text(errors="ignore") for path in bundle.rglob("*") if path.is_file())
        leaked = [key for key in ("pr_url", "post_fix_commit", "gold_patch_commit") if str(metadata.get(key, "")) and str(metadata[key]) in visible_text]
        return [f"model bundle leaks {key}" for key in leaked]


def main() -> int:
    failures: list[str] = []
    schema = json.loads((ROOT / "schemas/instance.schema.json").read_text())
    schema_task_types = set(schema["properties"]["task_type"]["enum"])
    schema_failure_modes = set(schema["properties"]["failure_modes"]["items"]["enum"])
    if schema_task_types != TASK_TYPES or schema_failure_modes != FAILURE_MODES: failures.append("schema controlled vocabularies differ from evaluator")
    if not (ROOT / "docs/instance_schema.md").exists(): failures.append("missing human-readable instance schema")
    source_text = (ROOT / "configs/sources.yaml").read_text()
    expected_sources = {"bluesky/ophyd", "bluesky/bluesky", "microsoft/Qcodes", "QCoDeS/Qcodes_contrib_drivers", "pymeasure/pymeasure", "instrumentkit/InstrumentKit", "areaDetector/areaDetector", "areaDetector/ADSimDetector", "micro-manager/micro-manager"}
    missing_sources = sorted(repo for repo in expected_sources if f"repo: {repo}" not in source_text)
    if missing_sources: failures.append(f"missing configured sources: {missing_sources}")
    candidates = json.loads((ROOT / "data/scored_candidates.json").read_text())
    candidate_errors = []
    for candidate in candidates:
        if not candidate.get("pr_url", "").startswith("https://github.com/"): candidate_errors.append(f"{candidate.get('candidate_id')}: missing PR")
        for key in ("pre_fix_commit", "post_fix_commit", "gold_patch_commit"):
            if not SHA.fullmatch(candidate.get(key, "")): candidate_errors.append(f"{candidate.get('candidate_id')}: invalid {key}")
        if candidate.get("task_type") not in TASK_TYPES: candidate_errors.append(f"{candidate.get('candidate_id')}: invalid task type")
        if not candidate.get("failure_modes") or not set(candidate["failure_modes"]) <= FAILURE_MODES: candidate_errors.append(f"{candidate.get('candidate_id')}: invalid failure modes")
        if candidate.get("requires_real_hardware") is not False: candidate_errors.append(f"{candidate.get('candidate_id')}: hardware dependency")
    candidate_summary = {"total": len(candidates), "verified_score": sum(c["score"] >= 80 for c in candidates), "linked_closed_issue": sum(bool(c.get("issue_url")) for c in candidates), "below_reserve": sum(c["score"] < 50 for c in candidates), "provenance_errors": candidate_errors}
    if candidate_summary["total"] != 20 or candidate_summary["verified_score"] < 5 or candidate_summary["linked_closed_issue"] < 5 or candidate_summary["below_reserve"] != 0 or candidate_errors: failures.append(f"candidate gates: {candidate_summary}")

    verified_results = {}
    for directory in sorted((ROOT / "data/verified_candidates").glob("iab_*")):
        missing = VERIFIED_FILES - {p.name for p in directory.iterdir()}
        errors = check_metadata(json.loads((directory / "candidate.json").read_text()), "verified_candidate")
        verified_results[directory.name] = {"passed": not missing and not errors, "missing": sorted(missing), "errors": errors}
        if missing or errors: failures.append(f"{directory.name} verified bundle invalid")
    if len(verified_results) != 5: failures.append(f"expected 5 verified candidates, got {len(verified_results)}")

    instance_results = {}
    for directory in sorted((ROOT / "instances").glob("iab_*")):
        present = {p.name for p in directory.iterdir() if p.name != ".work"}
        missing = INSTANCE_FILES - present
        source_errors = validate_source_snapshot(directory)
        boundary_errors = validate_model_boundary(directory)
        meta_errors = check_metadata(json.loads((directory / "instance.json").read_text()), "executable") + source_errors + boundary_errors
        setup = command(directory / "setup.sh")
        pre = command(directory / "reproduce_pre_fix.sh") if setup["passed"] else {"passed": False}
        reset = command(directory / "setup.sh")
        substitute = command(directory / "evaluate.sh", str(directory / "patches/gold.patch")) if reset["passed"] else {"passed": False}
        report_path = directory / ".work/evaluation_report.json"
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
        layers = report.get("layers", {})
        layer_gate = set(layers) == {"fail_to_pass", "regression", "state_trace", "minefields", "gold_differential"} and all(v.get("passed") for v in layers.values())
        passed = not missing and not meta_errors and setup["passed"] and pre["passed"] and substitute["passed"] and report.get("passed") is True and layer_gate
        instance_results[directory.name] = {"passed": passed, "missing": sorted(missing), "metadata_errors": meta_errors, "source_snapshot_verified": not source_errors, "model_boundary_verified": not boundary_errors, "pre_fix_failure_confirmed": pre.get("passed", False), "model_patch_substitution": substitute.get("passed", False), "json_report": report.get("passed") is True, "evaluation_layers": sorted(layers)}
        if not passed: failures.append(f"{directory.name} executable gate failed")
    if len(instance_results) != 3: failures.append(f"expected 3 executable instances, got {len(instance_results)}")

    unit_results = {}
    for test in sorted((ROOT / "tests").glob("test_*.py")) + sorted((ROOT / "evaluator/tests").glob("test_*.py")):
        proc = subprocess.run([sys.executable, str(ROOT / "evaluator/test_executor.py"), str(test)], cwd=ROOT, text=True, capture_output=True)
        unit_results[str(test.relative_to(ROOT))] = proc.returncode == 0
        if proc.returncode: failures.append(f"unit test failed: {test.relative_to(ROOT)}")

    result = {"passed": not failures, "candidate_summary": candidate_summary, "verified_candidates": verified_results, "executable_instances": instance_results, "unit_tests": unit_results, "failures": failures}
    target = ROOT / "reports/phase1_validation.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "report": str(target), "failures": failures}))
    return 0 if result["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
