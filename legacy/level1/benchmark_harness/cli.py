from __future__ import annotations

import argparse
import json
from pathlib import Path

from .docker_runtime import evaluate, generate
from .linting import lint_all, lint_instance
from .paths import ROOT, RUNS, parse_instance
from .run_store import create_run
from .security_check import run_security_check
from .world_distribution import freeze_distribution


def _run_dir(value: str) -> Path:
    path = (RUNS / value).resolve()
    if path.parent != RUNS.resolve() or not path.is_dir():
        raise argparse.ArgumentTypeError(f"unknown run id: {value}")
    return path


def _print_failures(failures: dict[str, list[str]]) -> None:
    for instance, errors in failures.items():
        print(instance)
        for error in errors:
            print(f"  - {error}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m benchmark_harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    lint_parser = subparsers.add_parser("lint-instance")
    lint_parser.add_argument("instance", nargs="?")

    security_parser = subparsers.add_parser("security-check")
    security_parser.add_argument("--instance", required=True)

    freeze_parser = subparsers.add_parser("freeze-worlds")
    freeze_parser.add_argument("--instance", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--instance", required=True)
    init_parser.add_argument("--agent", default="claude", choices=["claude"])
    init_parser.add_argument("--model", required=True)

    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--run", required=True, type=_run_dir)

    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--run", required=True, type=_run_dir)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--instance", required=True)
    run_parser.add_argument("--agent", default="claude", choices=["claude"])
    run_parser.add_argument("--model", required=True)

    args = parser.parse_args()
    if args.command == "lint-instance":
        if args.instance:
            source, instance_id = parse_instance(args.instance)
            errors = lint_instance(ROOT, source, instance_id)
            failures = {args.instance: errors} if errors else {}
        else:
            failures = lint_all(ROOT)
        if failures:
            _print_failures(failures)
            raise SystemExit(1)
        print("All model-visible instance files passed leakage checks.")
        return
    if args.command == "security-check":
        source, instance_id = parse_instance(args.instance)
        report = run_security_check(source, instance_id)
        print(json.dumps(report, indent=2))
        if not report["pass"]:
            raise SystemExit(1)
        return
    if args.command == "freeze-worlds":
        source, instance_id = parse_instance(args.instance)
        outputs = freeze_distribution(
            ROOT / "evaluations" / source / instance_id / "spec.json"
        )
        print(json.dumps({"worlds": [str(path.relative_to(ROOT)) for path in outputs]}, indent=2))
        return

    if args.command in {"init", "run"}:
        source, instance_id = parse_instance(args.instance)
        errors = lint_instance(ROOT, source, instance_id)
        if errors:
            _print_failures({args.instance: errors})
            raise SystemExit("instance leakage check failed")
        run_id, run_dir = create_run(source, instance_id, args.agent, args.model)
        print(json.dumps({"run_id": run_id, "run_dir": str(run_dir)}, indent=2))
        if args.command == "run":
            generate(run_dir)
            print(json.dumps(evaluate(run_dir), indent=2))
        return
    if args.command == "generate":
        generate(args.run)
        print(f"Generated {args.run / 'candidate/solution.py'}")
        return
    if args.command == "evaluate":
        print(json.dumps(evaluate(args.run), indent=2))


if __name__ == "__main__":
    main()
