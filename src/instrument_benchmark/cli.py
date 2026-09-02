from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contracts import ContractError, load_run_config
from .environment import load_repository_paths
from .orchestrator import run_benchmark


ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="instrument-benchmark")
    parser.add_argument("config", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        repository_paths = load_repository_paths(ROOT)
        report = run_benchmark(
            arguments.config,
            instrument_checkout=ROOT,
            repository_paths=repository_paths,
            allow_dirty=arguments.allow_dirty,
        )
    except ContractError as exc:
        print(f"invalid benchmark contract: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"benchmark infrastructure failure: {exc}", file=sys.stderr)
        return 3
    print(
        json.dumps(
            {
                "report": str(
                    load_run_config(arguments.config, repository_paths).report_path
                ),
                "score": report["score"],
                "strict_pass": report["strict_pass"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
