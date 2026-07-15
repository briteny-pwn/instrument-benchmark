from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any


DECIMAL = re.compile(r"(?<![A-Za-z0-9_.])([-+]?\d+\.\d+(?:[eE][-+]?\d+)?)")


def _delta(seed: str) -> float:
    number = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16)
    return 0.0007 + (number % 7) * 0.0001


def _serial_suffix(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:6].upper()


def _perturb_text(value: str, amount: float, suffix: str) -> str:
    if value.count(",") >= 2:
        fields = value.split(",")
        fields[2] = f"DEV-{suffix}"
        return ",".join(fields)
    if value.startswith("#"):
        return value

    def replace(match: re.Match[str]) -> str:
        original = match.group(1)
        precision = len(original.split(".", 1)[1].split("e", 1)[0].split("E", 1)[0])
        return f"{float(original) + amount:.{precision}f}"

    return DECIMAL.sub(replace, value)


def _mutate_json(value: Any, seed: str, key: str = "") -> Any:
    amount = _delta(seed)
    suffix = _serial_suffix(seed)
    if isinstance(value, dict):
        mutated = {child_key: _mutate_json(child, seed, str(child_key)) for child_key, child in value.items()}
        if key == "":
            mutated["_authoring"] = {"seed_digest": suffix, "scored": False}
        return mutated
    if isinstance(value, list):
        return [_mutate_json(child, seed, key) for child in value]
    if isinstance(value, str):
        if key in {"serial", "serial_number"}:
            return f"DEV-{suffix}"
        if key == "idn":
            return _perturb_text(value, amount, suffix)
        if key in {"response", "responses"}:
            return _perturb_text(value, amount, suffix)
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if key in {"slope", "dut_gain", "scale"}:
            return float(value) * 0.997
        if key.endswith("offset_v") or key in {"min", "max", "offset"}:
            return float(value) + amount
        if "noise" in key and isinstance(value, float):
            return float(value) + amount / 10
    return copy.deepcopy(value)


def materialize(base: Path, destination_dir: Path, seed: str) -> Path:
    """Create an unscored development scenario with distinct identity and values."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"authoring{base.suffix}"
    if base.suffix.lower() == ".json":
        data = json.loads(base.read_text(encoding="utf-8"))
        destination.write_text(
            json.dumps(_mutate_json(data, seed), indent=2) + "\n", encoding="utf-8"
        )
        return destination

    amount = _delta(seed)
    suffix = _serial_suffix(seed)
    lines: list[str] = [f"# unscored authoring scenario {suffix}"]
    for line in base.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\s+r\s*:", line):
            prefix, response = line.split(":", 1)
            quote = "'" if response.strip().startswith("'") and response.strip().endswith("'") else ""
            raw = response.strip().strip("'") if quote else response.strip()
            changed = _perturb_text(raw, amount, suffix)
            response = f" {quote}{changed}{quote}" if quote else f" {changed}"
            line = prefix + ":" + response
        lines.append(line)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination
