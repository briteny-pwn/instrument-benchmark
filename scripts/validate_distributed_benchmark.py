#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from instrument_benchmark.contracts import dump_json, load_run_config
from instrument_benchmark.environment import load_repository_paths
from instrument_benchmark.orchestrator import run_benchmark
from instrument_benchmark.evaluator_image import stage_evaluator_build_context


EXPECTED_IDENTITIES = {
    ("pyvisa", "pyvisa_dut_validation_v1"): 2,
    ("pyvisa", "pyvisa_dut_validation_v2"): 3,
}
EPHEMERAL_MOUNT_SOURCE = re.compile(
    rf"^{re.escape(str(Path(tempfile.gettempdir()).resolve()))}"
    r"/iab-[^/]+/w-[^/]+(?P<suffix>/(?:runner|workspace))?$"
)


def run_command(
    cwd: Path,
    arguments: list[str],
    *,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    completed = subprocess.run(
        arguments,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=environment,
        check=False,
    )
    return {
        "cwd": str(cwd),
        "command": arguments,
        "exit_code": completed.returncode,
        "output": completed.stdout[-16000:],
    }


def semantic_projection(value: Any) -> Any:
    if isinstance(value, dict):
        projection: dict[str, Any] = {}
        for key, item in value.items():
            if key in {
                "evidence_sequences",
                "validation",
                "provenance",
                "orchestration",
                "container_id",
                "created_at",
                "started_at",
                "finished_at",
                "stdout_sha256",
                "stderr_sha256",
                "report_sha256",
            }:
                continue
            if key == "mounts" and isinstance(item, list) and all(
                isinstance(mount, dict) for mount in item
            ):
                mounts = [
                    {
                        mount_key: (
                            _semantic_mount_source(mount_value)
                            if mount_key == "source"
                            else semantic_projection(mount_value)
                        )
                        for mount_key, mount_value in mount.items()
                    }
                    for mount in item
                ]
                projection[key] = sorted(
                    mounts,
                    key=lambda mount: json.dumps(
                        mount, sort_keys=True, separators=(",", ":")
                    ),
                )
            else:
                projection[key] = semantic_projection(item)
        return projection
    if isinstance(value, list):
        return [semantic_projection(item) for item in value]
    return value


def _semantic_mount_source(value: Any) -> Any:
    if not isinstance(value, str):
        return semantic_projection(value)
    match = EPHEMERAL_MOUNT_SOURCE.fullmatch(value)
    if match is None:
        return value
    return f"<iab-run>/<world>{match.group('suffix') or ''}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validate-distributed-benchmark")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(
            os.environ.get(
                "IAB_RUN_CONFIG",
                ROOT / "configs" / "pyvisa" / "pyvisa_dut_validation_v1.yaml",
            )
        ),
    )
    arguments = parser.parse_args(argv)
    config_path = arguments.config.resolve()
    repository_paths = load_repository_paths(ROOT)
    config = load_run_config(config_path, repository_paths)
    expected_report_schema = EXPECTED_IDENTITIES.get(
        (config.source_id, config.evaluator_id)
    )
    if expected_report_schema is None:
        raise RuntimeError(
            "validator requires a supported (source_id, evaluator_id) identity"
        )
    instance = config.instances_repo_path
    evaluator = config.evaluator_repo_path
    instance_root = (
        instance / "sources" / config.source_id / config.instance_id
    )
    instance_lock = __import__("yaml").safe_load(
        (instance_root / "image.lock.yaml").read_text(encoding="utf-8")
    )
    built_image = instance_lock["built_image"]
    commands = [
        run_command(
            ROOT,
            ["docker", "info", "--format", "{{.OSType}} {{.ServerVersion}}"],
        ),
        run_command(
            instance,
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        ),
        run_command(
            instance_root,
            [
                "docker", "buildx", "build", "--load", "--provenance=false",
                "--build-arg=SOURCE_DATE_EPOCH=0", "--network=none",
                "--platform=linux/amd64", "--label",
                f"iab.instance={config.instance_id}", "--label",
                f"iab.dockerfile-sha256={instance_lock['dockerfile_sha256']}",
                "--tag", built_image["reference"], "--file",
                str(instance_root / "Dockerfile"), str(instance_root),
            ],
        ),
        run_command(
            ROOT,
            [
                "docker", "image", "inspect", built_image["reference"],
                "--format", "{{.Id}}",
            ],
        ),
        run_command(
            ROOT,
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        ),
    ]
    first = run_benchmark(
        config_path,
        instrument_checkout=ROOT,
        repository_paths=repository_paths,
        allow_dirty=False,
    )
    manifest_output = ROOT / "reports" / "evaluator-build-manifest.json"
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="iab-manifest-") as directory:
        context = stage_evaluator_build_context(
            evaluator,
            evaluator / "container",
            Path(directory) / "context",
            source_id=config.source_id,
            evaluator_id=config.evaluator_id,
        )
        shutil.copy2(context.manifest_path, manifest_output)
    if config.evaluator_id == "pyvisa_dut_validation_v1":
        second = run_benchmark(
            config_path,
            instrument_checkout=ROOT,
            repository_paths=repository_paths,
            allow_dirty=True,
        )
        reproducible: bool | None = (
            semantic_projection(first) == semantic_projection(second)
        )
    else:
        reproducible = None
    world_count = len(first["worlds"])
    adversarial = _adversarial_cases(
        evaluator, config.source_id, config.evaluator_id
    )
    stale = run_command(
        ROOT,
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            (
                f"label=iab.owner={os.environ['IAB_CONTAINER_OWNER']}"
                if os.environ.get("IAB_CONTAINER_OWNER")
                else "label=iab.managed=true"
            ),
            "--format",
            "{{.ID}}",
        ],
    )
    commands.append(stale)
    native_linux = platform.system() == "Linux"
    docker_linux = (
        commands[0]["exit_code"] == 0
        and commands[0]["output"].strip().startswith("linux ")
    )
    no_stale_containers = not stale["output"].strip()
    candidate_image_matches_lock = (
        commands[3]["exit_code"] == 0
        and commands[3]["output"].strip() == built_image["digest"]
    )
    v2_invariants = _v2_invariants(first, config)
    passed = (
        native_linux
        and docker_linux
        and no_stale_containers
        and candidate_image_matches_lock
        and first.get("schema_version") == expected_report_schema
        and first.get("source_id") == config.source_id
        and all(command["exit_code"] == 0 for command in commands)
        and first["strict_pass"]
        and first["score"] == 100
        and first["fixed_world_pass_rate"] == 1.0
        and first["repeated_world_pass_rate"] == 1.0
        and world_count == 19
        and (reproducible is True or config.evaluator_id == "pyvisa_dut_validation_v2")
        and v2_invariants
    )
    first["validation"] = {
        "passed": passed,
        "semantic_reproducibility": reproducible,
        "world_count": world_count,
        "commands": commands,
        "adversarial_cases": [
            {
                "submission": case["submission"],
                "world": case["world"],
                "expected_status": case["expected_status"],
                "failed_gates": case["failed_gates"],
            }
            for case in adversarial
        ],
        "native_linux": native_linux,
        "docker_linux": docker_linux,
        "no_stale_containers": no_stale_containers,
        "candidate_image_matches_lock": candidate_image_matches_lock,
        "v2_formal_invariants": v2_invariants,
        "limitations": [
            "Simulation results do not prove transfer to physical hardware.",
            "Container isolation proves the benchmark boundary, not transfer "
            "to vendor drivers or physical buses.",
        ],
    }
    dump_json(config.report_path, first)
    print(
        json.dumps(
            {
                "passed": passed,
                "strict_pass": first["strict_pass"],
                "score": first["score"],
                "world_count": world_count,
                "semantic_reproducibility": reproducible,
                "report": str(config.report_path),
            },
            sort_keys=True,
        )
    )
    return 0 if passed else 1


def _adversarial_cases(
    evaluator: Path,
    source_id: str,
    evaluator_id: str,
) -> list[dict[str, Any]]:
    if evaluator_id == "pyvisa_dut_validation_v1":
        value = __import__("yaml").safe_load(
            (
                evaluator
                / "sources"
                / source_id
                / evaluator_id
                / "adversarial_matrix.yaml"
            ).read_text(encoding="utf-8")
        )
        return json.loads(json.dumps(value["cases"]))
    return [
        {
            "submission": "negatives/bad_protocol.py",
            "world": "nominal",
            "expected_status": "completed",
            "failed_gates": ["no_forbidden_access"],
        },
        {
            "submission": "negatives/leaked_sessions.py",
            "world": "nominal",
            "expected_status": "invalid_result",
            "failed_gates": ["active_close_all"],
        },
    ]


def _v2_invariants(first: dict[str, Any], config: Any) -> bool:
    if config.evaluator_id != "pyvisa_dut_validation_v2":
        return True
    reference = config.candidate_path.read_text(encoding="utf-8")
    worlds = first.get("worlds", [])
    evaluator_image = first.get("orchestration", {}).get("evaluator_image", {})
    outer = first.get("orchestration", {}).get("evaluator_container", {})
    return (
        first.get("schema_version") == 3
        and first.get("source_id") == config.source_id
        and first.get("evaluator", {}).get("source_id") == config.source_id
        and first.get("evaluator", {}).get("id") == config.evaluator_id
        and first.get("evaluator", {}).get("protocol_version") == 2
        and first.get("infrastructure_valid") is True
        and first.get("retry_eligible") is False
        and len(worlds) == 19
        and 'pyvisa.ResourceManager("@iab")' in reference
        and outer.get("image_id") == evaluator_image.get("image_id")
        and all(
            _complete_v2_world(world, evaluator_image.get("image_id"))
            for world in worlds
        )
    )


def _complete_v2_world(world: Any, evaluator_image_id: Any) -> bool:
    if not isinstance(world, dict):
        return False
    candidate = world.get("candidate_container_evidence")
    sim = world.get("sim_container_evidence")
    journal = world.get("sim_journal_evidence")
    if not all(isinstance(value, dict) for value in (candidate, sim, journal)):
        return False
    events = journal.get("events")
    return (
        candidate.get("cleanup_succeeded") is True
        and sim.get("cleanup_succeeded") is True
        and sim.get("image_digest") == evaluator_image_id
        and isinstance(events, list)
        and bool(events)
        and journal.get("event_count") == len(events)
        and isinstance(events[-1], dict)
        and events[-1].get("kind") == "lifecycle.exit"
        and any(
            isinstance(event, dict)
            and event.get("kind") == "lifecycle.finalized"
            for event in events
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
