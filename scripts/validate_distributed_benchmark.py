#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from instrument_benchmark.contracts import dump_json, load_run_config
from instrument_benchmark.orchestrator import run_benchmark


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
            }
        }
    if isinstance(value, list):
        return [semantic_projection(item) for item in value]
    return value


def main() -> int:
    instance = ROOT.parent / "instance"
    evaluator = ROOT.parent / "evaluator"
    config_path = ROOT / "configs" / "pyvisa_dut_validation_v1.yaml"
    config = load_run_config(config_path)
    docker_environment = dict(os.environ)
    docker_environment["IAB_RUN_DOCKER_TESTS"] = "1"
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
            evaluator,
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        ),
        run_command(
            evaluator,
            [
                sys.executable,
                "-m",
                "unittest",
                "tests.integration.test_container_image_linux",
                "tests.integration.test_container_isolation_linux",
                "tests.integration.test_docker_full_suite_linux",
                "-v",
            ],
            environment=docker_environment,
        ),
        run_command(
            evaluator,
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "evaluators/pyvisa_dut_validation_v1/tests",
                "-v",
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
            "name=^iab-",
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
    passed = (
        native_linux
        and docker_linux
        and no_stale_containers
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
