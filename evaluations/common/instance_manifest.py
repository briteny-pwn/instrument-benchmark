"""Canonical instance metadata and cross-boundary contract validation."""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


REGISTRY_PATH = Path("evaluations/registry.json")
CAPABILITIES = {
    "resource_discovery",
    "identity",
    "configuration",
    "ascii_parsing",
    "binary_parsing",
    "array_acquisition",
    "multi_instrument",
    "state_polling",
    "event_acquisition",
    "numeric_analysis",
    "decision",
    "safety_cleanup",
}
DIFFICULTY_FACTORS = {
    "dynamic_resources",
    "protocol_configuration",
    "binary_codec",
    "multi_device_coordination",
    "causal_state",
    "variable_length_data",
    "numeric_reconstruction",
    "timing_and_polling",
    "failure_branch",
}
BACKEND_FIDELITY = {"native", "ecosystem_simulator", "behavioral_emulation"}
JSON_PATH = re.compile(r"^\$(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")


@dataclass(frozen=True)
class InstanceManifest:
    source: str
    instance_id: str
    capabilities: tuple[str, ...]
    difficulty_factors: tuple[str, ...]
    backend_fidelity: dict[str, str]
    task_inputs: tuple[str, ...]
    observable_outputs: tuple[str, ...]
    safety_invariants: tuple[dict[str, str], ...]
    scenario_distribution: dict[str, Any]
    oracle_bindings: tuple[dict[str, str], ...]
    allowed_public_constants: tuple[Any, ...]

    @property
    def key(self) -> str:
        return f"{self.source}/{self.instance_id}"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "InstanceManifest":
        return cls(
            source=value["source"],
            instance_id=value["instance_id"],
            capabilities=tuple(value["capabilities"]),
            difficulty_factors=tuple(value["difficulty_factors"]),
            backend_fidelity=dict(value["backend_fidelity"]),
            task_inputs=tuple(value["task_inputs"]),
            observable_outputs=tuple(value["observable_outputs"]),
            safety_invariants=tuple(dict(item) for item in value["safety_invariants"]),
            scenario_distribution=dict(value["scenario_distribution"]),
            oracle_bindings=tuple(dict(item) for item in value["oracle_bindings"]),
            allowed_public_constants=tuple(value["allowed_public_constants"]),
        )


def load_registry(root: Path) -> dict[str, InstanceManifest]:
    data = json.loads((root / REGISTRY_PATH).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("evaluations/registry.json: unsupported schema_version")
    manifests = [InstanceManifest.from_dict(item) for item in data.get("instances", [])]
    registry = {manifest.key: manifest for manifest in manifests}
    if len(registry) != len(manifests):
        raise ValueError("evaluations/registry.json: duplicate source/instance_id")
    return registry


def _result_paths(value: Any, prefix: str = "$") -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}"
            yield path
            if isinstance(child, dict) and not ({"close", "range"} & set(child)):
                yield from _result_paths(child, path)


def validate_manifest(
    root: Path, manifest: InstanceManifest, spec: dict[str, Any], prompt: str
) -> list[str]:
    errors: list[str] = []
    label = manifest.key
    if spec.get("instance_id") != manifest.instance_id:
        errors.append(f"{label}: registry instance_id disagrees with spec")
    unknown = set(manifest.capabilities) - CAPABILITIES
    if unknown:
        errors.append(f"{label}: unknown capability labels {sorted(unknown)}")
    unknown = set(manifest.difficulty_factors) - DIFFICULTY_FACTORS
    if unknown:
        errors.append(f"{label}: unknown difficulty factors {sorted(unknown)}")
    fidelity = manifest.backend_fidelity
    if fidelity.get("level") not in BACKEND_FIDELITY:
        errors.append(f"{label}: invalid backend_fidelity.level")
    if fidelity.get("backend") != spec.get("gateway"):
        errors.append(f"{label}: backend_fidelity.backend disagrees with spec gateway")

    checks = {check.get("name"): check for check in spec.get("checks", [])}
    for path in (*manifest.task_inputs, *manifest.observable_outputs):
        if not JSON_PATH.fullmatch(path):
            errors.append(f"{label}: invalid result path {path!r}")
        field = path.rsplit(".", 1)[-1]
        if not re.search(rf"\b{re.escape(field)}\b", prompt):
            errors.append(f"{label}: prompt does not declare result field {field!r}")

    outputs = set(manifest.observable_outputs)
    bound_outputs: set[str] = set()
    for binding in manifest.oracle_bindings:
        output = binding.get("output")
        check_name = binding.get("check")
        if output not in outputs:
            errors.append(f"{label}: oracle binding references undeclared output {output!r}")
        if check_name not in checks:
            errors.append(f"{label}: oracle binding references missing check {check_name!r}")
        else:
            check_type = checks[check_name].get("type", "")
            if check_type in {"result_json", "trace_coverage", "ordered_milestones"}:
                errors.append(f"{label}: {check_name!r} is not an independent oracle check")
        if output:
            bound_outputs.add(output)
    unbound = outputs - bound_outputs
    if unbound:
        errors.append(f"{label}: observable outputs lack oracle bindings {sorted(unbound)}")

    safety_checks = {item.get("check") for item in manifest.safety_invariants}
    for check_name in safety_checks:
        if check_name not in checks:
            errors.append(f"{label}: safety invariant references missing check {check_name!r}")
    if "cleanup" not in safety_checks:
        errors.append(f"{label}: safety invariants must bind cleanup")

    scenarios = spec.get("scenarios", [])
    distribution = manifest.scenario_distribution
    if distribution.get("kind") not in {"hand_authored", "parameterized"}:
        errors.append(f"{label}: invalid scenario_distribution.kind")
    generated_worlds = spec.get("world_distribution", {}).get("worlds", [])
    active_worlds = generated_worlds if distribution.get("kind") == "parameterized" else scenarios
    if distribution.get("kind") == "parameterized" and not generated_worlds:
        errors.append(f"{label}: registry declares parameterized worlds but spec has no world_distribution")
    if distribution.get("kind") == "hand_authored" and generated_worlds:
        errors.append(f"{label}: spec has world_distribution but registry declares hand_authored worlds")
    if len(active_worlds) < distribution.get("minimum_hidden_worlds", 0):
        errors.append(f"{label}: fewer hidden scenarios than declared")
    scenario_ids = [scenario.get("id") for scenario in active_worlds]
    if len(set(scenario_ids)) != len(scenario_ids) or any(not item for item in scenario_ids):
        errors.append(f"{label}: hidden scenario ids must be non-empty and unique")
    if not distribution.get("variation_dimensions"):
        errors.append(f"{label}: scenario distribution needs variation dimensions")
    if generated_worlds:
        from benchmark_harness.world_distribution import GROUPS, materialize_world

        world_distribution = spec["world_distribution"]
        if world_distribution.get("version") != 1:
            errors.append(f"{label}: unsupported world_distribution version")
        if world_distribution.get("materialization") != "frozen":
            errors.append(f"{label}: parameterized worlds must use frozen materialization")
        groups = {world.get("group") for world in generated_worlds}
        if groups != set(GROUPS):
            errors.append(f"{label}: world_distribution must contain core, generalization, and adversarial groups")
        seeds = [world.get("seed") for world in generated_worlds]
        if any(not seed for seed in seeds) or len(set(seeds)) != len(seeds):
            errors.append(f"{label}: world seeds must be non-empty and unique")
        evaluation_dir = root / "evaluations" / manifest.source / manifest.instance_id
        with tempfile.TemporaryDirectory(prefix="instance-world-validation-") as tmpdir:
            for index, world in enumerate(generated_worlds):
                template = evaluation_dir / str(world.get("template", ""))
                frozen = evaluation_dir / str(world.get("simulator", ""))
                if not template.is_file():
                    errors.append(f"{label}: missing world template {world.get('template')!r}")
                    continue
                if not frozen.is_file():
                    errors.append(f"{label}: missing frozen world {world.get('simulator')!r}")
                    continue
                try:
                    regenerated = materialize_world(
                        evaluation_dir, world, Path(tmpdir) / f"{index}{frozen.suffix}"
                    )
                except (KeyError, OSError, TypeError, ValueError) as exc:
                    errors.append(f"{label}: cannot materialize world {world.get('id')!r}: {exc}")
                    continue
                if regenerated.read_bytes() != frozen.read_bytes():
                    errors.append(f"{label}: frozen world {world.get('simulator')!r} is stale")

    authoring = spec.get("authoring", {})
    authoring_path = authoring.get("base_simulator")
    hidden_paths = {world.get("simulator") for world in active_worlds}
    if not authoring_path or not authoring.get("seed"):
        errors.append(f"{label}: missing authoring source or seed")
    elif not (root / "evaluations" / manifest.source / manifest.instance_id / authoring_path).is_file():
        errors.append(f"{label}: authoring source does not exist")
    if authoring.get("materialized") is not True:
        errors.append(f"{label}: authoring must explicitly require unscored materialization")
    elif authoring_path:
        from benchmark_harness.authoring import materialize as materialize_authoring

        evaluation_dir = root / "evaluations" / manifest.source / manifest.instance_id
        base = evaluation_dir / authoring_path
        if base.is_file():
            with tempfile.TemporaryDirectory(prefix="instance-authoring-validation-") as tmpdir:
                generated = materialize_authoring(base, Path(tmpdir), str(authoring["seed"]))
                for hidden_path in hidden_paths:
                    hidden = evaluation_dir / str(hidden_path)
                    if hidden.is_file() and generated.read_bytes() == hidden.read_bytes():
                        errors.append(
                            f"{label}: materialized authoring world duplicates hidden world {hidden_path!r}"
                        )

    public_constants = spec.get("public_constants", list(manifest.allowed_public_constants))
    if public_constants != list(manifest.allowed_public_constants):
        errors.append(f"{label}: spec public_constants disagrees with registry")
    return errors


def validate_registry(root: Path) -> list[str]:
    errors: list[str] = []
    try:
        registry = load_registry(root)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return [str(exc)]
    instance_keys = {
        f"{path.parent.name}/{path.name}"
        for path in (root / "instances").glob("*/*")
        if path.is_dir()
    }
    evaluation_keys = {
        f"{path.parent.parent.name}/{path.parent.name}"
        for path in (root / "evaluations").glob("*/*/spec.json")
    }
    registry_keys = set(registry)
    if registry_keys != instance_keys:
        errors.append(
            "registry/instances mismatch: "
            f"missing={sorted(instance_keys - registry_keys)}, extra={sorted(registry_keys - instance_keys)}"
        )
    if registry_keys != evaluation_keys:
        errors.append(
            "registry/evaluations mismatch: "
            f"missing={sorted(evaluation_keys - registry_keys)}, extra={sorted(registry_keys - evaluation_keys)}"
        )
    authoring_seeds: dict[str, str] = {}
    for key, manifest in registry.items():
        spec_path = root / "evaluations" / manifest.source / manifest.instance_id / "spec.json"
        prompt_path = root / "instances" / manifest.source / manifest.instance_id / "prompt.md"
        if not spec_path.is_file() or not prompt_path.is_file():
            continue
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{key}: invalid spec: {exc}")
            continue
        errors.extend(
            validate_manifest(root, manifest, spec, prompt_path.read_text(encoding="utf-8"))
        )
        authoring = spec.get("authoring", {})
        seed = authoring.get("seed")
        if seed in authoring_seeds:
            errors.append(
                f"{key}: authoring seed is also used by {authoring_seeds[seed]}"
            )
        elif seed:
            authoring_seeds[seed] = key
        base_name = authoring.get("base_simulator")
        if base_name:
            try:
                from benchmark_harness.authoring import materialize

                base = spec_path.parent / base_name
                with tempfile.TemporaryDirectory() as tmpdir:
                    output = materialize(base, Path(tmpdir), seed)
                    materialized = output.read_bytes()
                hidden_definitions = {
                    (spec_path.parent / scenario["simulator"]).read_bytes()
                    for scenario in spec.get("scenarios", [])
                }
                if materialized in hidden_definitions:
                    errors.append(
                        f"{key}: authoring materialization duplicates a hidden backend definition"
                    )
            except (KeyError, OSError, TypeError, ValueError) as exc:
                errors.append(f"{key}: cannot verify authoring separation: {exc}")
    return errors
