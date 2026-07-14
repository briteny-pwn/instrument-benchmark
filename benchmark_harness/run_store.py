from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
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
    manifest = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "instance": f"{source}/{instance_id}",
        "agent": agent,
        "model": model,
        "git_revision": _git_revision(),
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
