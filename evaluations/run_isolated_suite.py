"""Run reference candidates through the official Docker collected-evidence path."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from benchmark_harness.docker_runtime import evaluate
from benchmark_harness.paths import ROOT
from benchmark_harness.run_store import write_json


def _available_instances() -> list[str]:
    return [
        f"{spec.parent.parent.name}/{spec.parent.name}"
        for spec in sorted((ROOT / "evaluations").glob("*/*/spec.json"))
    ]


def run_reference(instance: str) -> dict[str, object]:
    source, instance_id = instance.split("/", 1)
    reference = (
        ROOT
        / "evaluations"
        / source
        / instance_id
        / "reference_solution"
        / "experiment.py"
    )
    if not reference.is_file():
        raise ValueError(f"{instance}: reference solution is missing")
    with tempfile.TemporaryDirectory(prefix="instrument-isolated-reference-") as tmpdir:
        run_dir = Path(tmpdir)
        (run_dir / "candidate").mkdir()
        (run_dir / "evaluation").mkdir()
        shutil.copy2(reference, run_dir / "candidate" / "solution.py")
        write_json(
            run_dir / "manifest.json",
            {
                "manifest_version": 2,
                "run_id": f"isolated-reference-{instance_id}",
                "instance": instance,
                "agent": "reference",
                "model": "reference",
                "image_digests": {},
                "status": "generated",
            },
        )
        return evaluate(run_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exercise reference solutions in the official Docker evaluator."
    )
    parser.add_argument(
        "--instance",
        action="append",
        choices=_available_instances(),
        help="SOURCE/INSTANCE to run; repeat for more than one",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="run all instances (slow; intended for release validation)",
    )
    args = parser.parse_args()
    if args.all and args.instance:
        parser.error("use either --all or --instance")
    instances = _available_instances() if args.all else args.instance
    if not instances:
        parser.error("provide --instance or --all")

    failures: list[str] = []
    for instance in instances:
        report = run_reference(instance)
        passed = report.get("pass") is True
        print(
            json.dumps(
                {
                    "instance": instance,
                    "pass": passed,
                    "total": report.get("total"),
                    "pass_rate": report.get("pass_rate"),
                },
                sort_keys=True,
            )
        )
        if not passed:
            failures.append(instance)
    if failures:
        raise SystemExit(f"isolated reference failures: {', '.join(failures)}")


if __name__ == "__main__":
    main()
