#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import platform
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
from instrument_benchmark.orchestrator import run_benchmark
from instrument_benchmark.evaluator_image import stage_evaluator_build_context


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
        return {
            key: semantic_projection(item)
            for key, item in value.items()
            if key
            not in {
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
            }
        }
    if isinstance(value, list):
        return [semantic_projection(item) for item in value]
    return value


def main() -> int:
    instance = Path(os.environ.get("IAB_INSTANCE_CHECKOUT", ROOT.parent / "instance"))
    evaluator = Path(os.environ.get("IAB_EVALUATOR_CHECKOUT", ROOT.parent / "evaluator"))
    config_path = Path(
        os.environ.get(
            "IAB_RUN_CONFIG", ROOT / "configs" / "pyvisa_dut_validation_v1.yaml"
        )
    )
    config = load_run_config(config_path)
    instance_root = instance / "pyvisa_dut_validation_v1"
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
                "iab.instance=pyvisa_dut_validation_v1", "--label",
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
    manifest_output = ROOT / "reports" / "evaluator-build-manifest.json"
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="iab-manifest-") as directory:
        context = stage_evaluator_build_context(
            evaluator, ROOT / "container", Path(directory) / "context"
        )
        shutil.copy2(context.manifest_path, manifest_output)
    first = run_benchmark(
        config_path,
        instrument_checkout=ROOT,
        allow_dirty=False,
    )
    second = run_benchmark(
        config_path,
        instrument_checkout=ROOT,
        allow_dirty=True,
    )
    reproducible = semantic_projection(first) == semantic_projection(second)
    world_count = len(first["worlds"])
    adversarial = json.loads(
        json.dumps(
            __import__("yaml").safe_load(
                (
                    evaluator
                    / "evaluators"
                    / "pyvisa_dut_validation_v1"
                    / "adversarial_matrix.yaml"
                ).read_text(encoding="utf-8")
            )["cases"]
        )
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
    passed = (
        native_linux
        and docker_linux
        and no_stale_containers
        and candidate_image_matches_lock
        and all(command["exit_code"] == 0 for command in commands)
        and first["strict_pass"]
        and first["score"] == 100
        and first["fixed_world_pass_rate"] == 1.0
        and first["repeated_world_pass_rate"] == 1.0
        and world_count == 19
        and reproducible
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


if __name__ == "__main__":
    raise SystemExit(main())
