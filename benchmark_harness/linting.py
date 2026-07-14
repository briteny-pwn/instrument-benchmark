from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from .paths import EVALUATIONS, INSTANCES


VISIBLE_FILES = {
    Path("prompt.md"),
    Path("environment/instrument_manual.md"),
    Path("environment/simulator_protocol.md"),
}

LEAK_PATTERNS = {
    "evaluation framing": re.compile(r"\b(?:benchmark|evaluator|evaluation|grader|grading)\b", re.I),
    "scoring details": re.compile(
        r"\b(?:score|scoring|rubric|pass[_ -]?threshold|scoring gate|trace[_ -]?coverage|milestone)\b", re.I
    ),
    "hidden implementation": re.compile(r"\b(?:reference[_ -]?solution|hidden scenario|hidden transfer)\b", re.I),
}

SERIAL_TOKEN = re.compile(r"\b[A-Z][A-Z0-9_-]*\d{2,}[A-Z0-9_-]*\b")


def _load_data(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    except (OSError, json.JSONDecodeError, yaml.YAMLError):
        return None


def _walk(value: Any, key: str = "") -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for child_key, child in value.items():
            if isinstance(child_key, str) and ("::" in child_key or "://" in child_key):
                items.append(("__mapping_key__", child_key))
            items.extend(_walk(child, str(child_key)))
    elif isinstance(value, list):
        for child in value:
            items.extend(_walk(child, key))
    else:
        items.append((key, value))
    return items


def _sensitive_hidden_strings(evaluation_dir: Path, public_constants: set[str]) -> set[str]:
    sensitive: set[str] = set()
    paths = [*evaluation_dir.rglob("*.json"), *evaluation_dir.rglob("*.yaml"), *evaluation_dir.rglob("*.yml")]
    for path in paths:
        data = _load_data(path)
        for key, value in _walk(data):
            if not isinstance(value, str) or value in public_constants:
                continue
            normalized_key = key.lower()
            if normalized_key in {"resource", "resources", "serial", "serial_number"}:
                sensitive.add(value)
            if normalized_key == "name" and ("::" in value or "://" in value):
                sensitive.add(value)
            if normalized_key == "__mapping_key__":
                sensitive.add(value)
            if normalized_key in {"response", "idn"} and value.count(",") >= 2:
                sensitive.add(value)
            sensitive.update(SERIAL_TOKEN.findall(value))
    return {item for item in sensitive if len(item) >= 5 and item not in public_constants}


def lint_instance(root: Path, source: str, instance_id: str) -> list[str]:
    instance_dir = root / "instances" / source / instance_id
    evaluation_dir = root / "evaluations" / source / instance_id
    errors: list[str] = []
    if not instance_dir.is_dir():
        return [f"unknown instance: {source}/{instance_id}"]

    actual: set[Path] = set()
    for path in instance_dir.rglob("*"):
        if path.is_symlink():
            errors.append(f"{path.relative_to(instance_dir)}: symlinks are not allowed")
        elif path.is_file() and path.name != ".DS_Store":
            actual.add(path.relative_to(instance_dir))
    for path in sorted(VISIBLE_FILES - actual):
        errors.append(f"missing visible file: {path}")
    for path in sorted(actual - VISIBLE_FILES):
        errors.append(f"unexpected visible file: {path}")

    spec = _load_data(evaluation_dir / "spec.json") or {}
    public_constants = {str(value) for value in spec.get("public_constants", [])}
    sensitive = _sensitive_hidden_strings(evaluation_dir, public_constants)
    for relative in sorted(actual & VISIBLE_FILES):
        path = instance_dir / relative
        text = path.read_text(encoding="utf-8")
        for label, pattern in LEAK_PATTERNS.items():
            match = pattern.search(text)
            if match:
                errors.append(f"{relative}: contains {label}: {match.group(0)!r}")
        for secret in sorted(sensitive, key=len, reverse=True):
            if secret in text:
                errors.append(f"{relative}: repeats hidden scenario identifier {secret!r}")

    prompt = instance_dir / "prompt.md"
    if prompt.exists():
        text = prompt.read_text(encoding="utf-8")
        if "solution.py" not in text or "run_experiment" not in text:
            errors.append("prompt.md: missing solution.py/run_experiment output contract")
    return errors


def lint_all(root: Path) -> dict[str, list[str]]:
    failures: dict[str, list[str]] = {}
    for instance_dir in sorted((root / "instances").glob("*/*")):
        if not instance_dir.is_dir():
            continue
        key = f"{instance_dir.parent.name}/{instance_dir.name}"
        errors = lint_instance(root, instance_dir.parent.name, instance_dir.name)
        if errors:
            failures[key] = errors
    return failures
