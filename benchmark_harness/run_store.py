from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .linting import VISIBLE_FILES
from .paths import ROOT, RUNS


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_revision() -> str | None:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False
    )
    return process.stdout.strip() if process.returncode == 0 else None


def _git_dirty() -> bool | None:
    process = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=False
    )
    return bool(process.stdout.strip()) if process.returncode == 0 else None


def _benchmark_release(revision: str | None) -> str:
    configured = os.environ.get("BENCHMARK_RELEASE")
    if configured:
        return configured
    process = subprocess.run(
        ["git", "describe", "--tags", "--exact-match"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode == 0:
        return process.stdout.strip()
    return f"unreleased+{revision[:12]}" if revision else "unreleased+unknown"


def _relative_hash(path: Path) -> dict[str, str]:
    return {"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)}


def _release_inputs(source: str, instance_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    evaluation = ROOT / "evaluations" / source / instance_id
    spec_path = evaluation / "spec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    scenario_paths: set[Path] = set()
    for scenario in spec.get("scenarios", []):
        simulator = scenario.get("simulator")
        if simulator and (evaluation / simulator).is_file():
            scenario_paths.add(evaluation / simulator)
    generated_worlds = spec.get("world_distribution", {}).get("worlds", [])
    for world in generated_worlds:
        for field in ("template", "simulator"):
            relative = world.get(field)
            if relative and (evaluation / relative).is_file():
                scenario_paths.add(evaluation / relative)
    authoring = spec.get("authoring", {})
    base_simulator = authoring.get("base_simulator")
    if base_simulator and (evaluation / base_simulator).is_file():
        scenario_paths.add(evaluation / base_simulator)

    generator_paths = [
        ROOT / "benchmark_harness" / "authoring.py",
        ROOT / "benchmark_harness" / "world_distribution.py",
        ROOT / "benchmark_harness" / "simulator_service.py",
        ROOT / "evaluations" / "common" / "instance_manifest.py",
        ROOT / "evaluations" / "common" / "grader_core.py",
    ]
    generators = [_relative_hash(path) for path in generator_paths if path.is_file()]
    lock_paths = [
        path
        for path in (
            ROOT / "requirements.lock",
            ROOT / "uv.lock",
            ROOT / "poetry.lock",
            ROOT / "Pipfile.lock",
            ROOT / "package-lock.json",
        )
        if path.is_file()
    ]
    manifest_paths = [path for path in (ROOT / "requirements.txt",) if path.is_file()]
    inputs = {
        "spec": _relative_hash(spec_path),
        "scenarios": [_relative_hash(path) for path in sorted(scenario_paths)],
        "generators": generators,
        "dependency_lock": {
            "status": "locked" if lock_paths else "missing",
            "files": [_relative_hash(path) for path in lock_paths],
        },
        "dependency_manifests": [_relative_hash(path) for path in manifest_paths],
    }
    evaluation_worlds = generated_worlds or spec.get("scenarios", [])
    seeds = {
        "authoring": authoring.get("seed"),
        "model": None,
        "evaluation": {
            str(world.get("id", f"scenario-{index + 1}")): world.get("seed")
            for index, world in enumerate(evaluation_worlds)
        },
    }
    return inputs, seeds


def create_run(source: str, instance_id: str, agent: str, model: str) -> tuple[str, Path]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]
    run_dir = RUNS / run_id
    workspace = run_dir / "workspace"
    for relative in VISIBLE_FILES:
        destination = workspace / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "instances" / source / instance_id / relative, destination)
    workspace.chmod(0o777)
    (run_dir / "candidate").mkdir(parents=True)
    (run_dir / "agent").mkdir(parents=True)
    (run_dir / "evaluation").mkdir(parents=True)
    revision = _git_revision()
    release_inputs, seeds = _release_inputs(source, instance_id)
    manifest = {
        "manifest_version": 2,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "instance": f"{source}/{instance_id}",
        "agent": agent,
        "model": model,
        "benchmark_release": _benchmark_release(revision),
        "git_revision": revision,
        "git_dirty": _git_dirty(),
        "release_inputs": release_inputs,
        "seeds": seeds,
        "image_digests": {},
        "runtime": {
            "orchestrator": "benchmark_harness",
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "container_engine": "docker",
        },
        "model_metadata": {
            "provider": os.environ.get("BENCHMARK_MODEL_PROVIDER"),
            "adapter": agent,
            "model_id": model,
        },
        "decoding": {
            "temperature": None,
            "top_p": None,
            "max_tokens": None,
            "seed": None,
            "status": "not_exposed_by_agent_adapter",
        },
        "status": "initialized",
    }
    write_json(run_dir / "manifest.json", manifest)
    update_hashes(run_dir)
    return run_id, run_dir


def load_manifest(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))


def update_manifest(run_dir: Path, **changes: Any) -> None:
    manifest = load_manifest(run_dir)
    manifest.update(changes)
    write_json(run_dir / "manifest.json", manifest)


def update_hashes(run_dir: Path) -> None:
    files = {}
    for relative in [*sorted(VISIBLE_FILES), Path("candidate/solution.py"), Path("evaluation/report.json")]:
        path = run_dir / (Path("workspace") / relative if relative in VISIBLE_FILES else relative)
        if path.is_file():
            files[str(relative)] = _sha256(path)
    write_json(run_dir / "hashes.json", {"sha256": files})


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
