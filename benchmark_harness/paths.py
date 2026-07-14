from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTANCES = ROOT / "instances"
EVALUATIONS = ROOT / "evaluations"
RUNS = ROOT / "runs"


def parse_instance(value: str) -> tuple[str, str]:
    parts = Path(value).parts
    if len(parts) != 2 or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("instance must have the form SOURCE/INSTANCE_ID")
    source, instance_id = parts
    if not (INSTANCES / source / instance_id).is_dir():
        raise ValueError(f"unknown instance: {value}")
    return source, instance_id


def evaluation_dir(source: str, instance_id: str) -> Path:
    return EVALUATIONS / source / instance_id
