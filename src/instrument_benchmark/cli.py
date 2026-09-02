from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contracts import ContractError, load_run_config
from .environment import load_repository_paths
from .orchestrator import run_benchmark
from .suite import load_suite_config, run_suite


ROOT = Path(__file__).resolve().parents[2]


def _normalize_legacy_args(command_line: list[str]) -> list[str]:
    if not command_line or command_line[0] == "run":
        return command_line

    for index, argument in enumerate(command_line):
        if not argument.startswith("-"):
            return [
                "run",
                "--config",
                argument,
                *command_line[:index],
                *command_line[index + 1 :],
            ]
    return command_line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="instrbench")
    subcommands = parser.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run")
    target = run.add_mutually_exclusive_group(required=True)
    target.add_argument("--config", type=Path)
    target.add_argument("--suite", type=Path)
    run.add_argument("--allow-dirty", action="store_true")

    command_line = _normalize_legacy_args(list(sys.argv[1:] if argv is None else argv))
    arguments = parser.parse_args(command_line)
    try:
        repository_paths = load_repository_paths(ROOT)
        if arguments.suite is not None:
            suite = load_suite_config(arguments.suite, repository_paths)
            execution = run_suite(
                suite,
                instrument_checkout=ROOT,
                repository_paths=repository_paths,
                allow_dirty=arguments.allow_dirty,
            )
            output = {
                "report": str(suite.result_path),
                "summary": execution.report["summary"],
            }
            exit_status = 3 if execution.has_infrastructure_failures else 0
        else:
            report = run_benchmark(
                arguments.config,
                instrument_checkout=ROOT,
                repository_paths=repository_paths,
                allow_dirty=arguments.allow_dirty,
            )
            output = {
                "report": str(
                    load_run_config(arguments.config, repository_paths).report_path
                ),
                "score": report["score"],
                "strict_pass": report["strict_pass"],
            }
            exit_status = 0
    except ContractError as exc:
        print(f"invalid benchmark contract: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"benchmark infrastructure failure: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(output, sort_keys=True))
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main())
