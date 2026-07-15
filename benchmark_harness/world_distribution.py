from __future__ import annotations

import copy
import hashlib
import json
import random
from pathlib import Path
from typing import Any

import yaml


GROUPS = ("core", "generalization", "adversarial")


class WorldDistributionError(ValueError):
    pass


def _rng(seed: str) -> random.Random:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _resolve(value: Any, rng: random.Random) -> Any:
    if isinstance(value, dict) and set(value) == {"choice"}:
        choices = value["choice"]
        if not isinstance(choices, list) or not choices:
            raise WorldDistributionError("choice must be a non-empty list")
        return copy.deepcopy(choices[rng.randrange(len(choices))])
    if isinstance(value, dict):
        return {key: _resolve(child, rng) for key, child in value.items()}
    if isinstance(value, list):
        return [_resolve(child, rng) for child in value]
    return copy.deepcopy(value)


def _set_path(document: Any, path: str, value: Any) -> None:
    if not path.startswith("/"):
        raise WorldDistributionError(f"patch path must be a JSON pointer: {path!r}")
    parts = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
    target = document
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    leaf = parts[-1]
    if isinstance(target, list):
        target[int(leaf)] = value
    else:
        target[leaf] = value


def _load(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)


def _dump(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        text = json.dumps(document, indent=2) + "\n"
    else:
        text = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")


def materialize_world(
    evaluation_dir: Path,
    world: dict[str, Any],
    destination: Path,
) -> Path:
    """Materialize one simulator file deterministically from a template and seed."""
    seed = str(world.get("seed", ""))
    if not seed:
        raise WorldDistributionError("world seed is required")
    group = world.get("group")
    if group not in GROUPS:
        raise WorldDistributionError(f"world group must be one of {GROUPS}")
    template = evaluation_dir / str(world["template"])
    document = _load(template)
    rng = _rng(seed)
    for patch in world.get("patches", []):
        _set_path(document, str(patch["path"]), _resolve(patch["value"], rng))
    _dump(destination, document)
    return destination


def freeze_distribution(spec_path: Path, destination_dir: Path | None = None) -> list[Path]:
    """Write all declared worlds and return their frozen simulator paths."""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    distribution = spec.get("world_distribution")
    if not distribution:
        raise WorldDistributionError("spec has no world_distribution")
    if int(distribution.get("version", 0)) != 1:
        raise WorldDistributionError("unsupported world_distribution version")
    evaluation_dir = spec_path.parent
    root = destination_dir or evaluation_dir
    outputs: list[Path] = []
    seen: set[tuple[str, str]] = set()
    for world in distribution.get("worlds", []):
        identity = (str(world.get("group")), str(world.get("seed")))
        if identity in seen:
            raise WorldDistributionError(f"duplicate group/seed pair: {identity}")
        seen.add(identity)
        output = root / str(world["simulator"])
        outputs.append(materialize_world(evaluation_dir, world, output))
    missing = set(GROUPS) - {str(world.get("group")) for world in distribution.get("worlds", [])}
    if missing:
        raise WorldDistributionError(f"distribution is missing groups: {sorted(missing)}")
    return outputs


def distribution_scenarios(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose generated worlds through the existing scenario/spec contract."""
    distribution = spec.get("world_distribution")
    if not distribution:
        return list(spec.get("scenarios", []))
    scenarios = []
    for index, world in enumerate(distribution.get("worlds", [])):
        scenario = {
            key: copy.deepcopy(value)
            for key, value in world.items()
            if key not in {"template", "patches", "seed"}
        }
        scenario.setdefault("id", f"{world['group']}-{index + 1}")
        scenario["world_group"] = world["group"]
        scenario["world_seed"] = world["seed"]
        scenarios.append(scenario)
    return scenarios
