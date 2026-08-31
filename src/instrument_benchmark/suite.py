from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from .contracts import ContractError, RunConfig, dump_json, load_run_config
from .environment import RepositoryPaths
from .orchestrator import run_benchmark


_IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]*")


@dataclass(frozen=True)
class SuiteEntry:
    config_path: Path
    config: RunConfig


@dataclass(frozen=True)
class SuiteConfig:
    schema_version: int
    suite_id: str
    suite_path: Path
    entries: tuple[SuiteEntry, ...]
    result_path: Path


BenchmarkRunner = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class SuiteExecution:
    report: dict[str, Any]
    has_infrastructure_failures: bool


def load_suite_config(path: Path, repository_paths: RepositoryPaths) -> SuiteConfig:
    try:
        suite_path = path.resolve()
        value = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    except (OSError, RuntimeError, ValueError, yaml.YAMLError) as exc:
        raise ContractError(f"cannot load suite config: {exc}") from exc
    _validate_contract(value)

    root = suite_path.parent
    run_paths = tuple(_resolve(root, run_path) for run_path in value["runs"])
    if len(set(run_paths)) != len(run_paths):
        raise ContractError("duplicate run path in suite")

    entries = tuple(
        SuiteEntry(
            config_path=run_path,
            config=load_run_config(run_path, repository_paths),
        )
        for run_path in run_paths
    )
    run_ids = tuple(entry.config.run_id for entry in entries)
    if len(set(run_ids)) != len(run_ids):
        raise ContractError("duplicate run_id in suite")
    report_paths = tuple(entry.config.report_path for entry in entries)
    if len(set(report_paths)) != len(report_paths):
        raise ContractError("duplicate run report_path in suite")

    result_path = _resolve(root, value["result_path"])
    if result_path in report_paths:
        raise ContractError("suite result_path collides with a run report_path")
    return SuiteConfig(
        schema_version=1,
        suite_id=value["suite_id"],
        suite_path=suite_path,
        entries=entries,
        result_path=result_path,
    )


def run_suite(
    config: SuiteConfig,
    *,
    instrument_checkout: Path,
    repository_paths: RepositoryPaths,
    allow_dirty: bool = False,
    benchmark_runner: BenchmarkRunner = run_benchmark,
) -> SuiteExecution:
    runs: list[dict[str, Any]] = []
    infrastructure_failures = 0

    for index, entry in enumerate(config.entries):
        run = {
            "index": index,
            "config_path": str(entry.config_path),
            "run_id": entry.config.run_id,
            "source_id": entry.config.source_id,
            "instance_id": entry.config.instance_id,
            "evaluator_id": entry.config.evaluator_id,
            "report_path": str(entry.config.report_path),
        }
        try:
            result = benchmark_runner(
                entry.config_path,
                instrument_checkout=instrument_checkout,
                repository_paths=repository_paths,
                allow_dirty=allow_dirty,
            )
        except Exception as exc:
            infrastructure_failures += 1
            runs.append(
                {
                    **run,
                    "status": "infrastructure_error",
                    "score": None,
                    "strict_pass": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        else:
            runs.append(
                {
                    **run,
                    "status": "completed",
                    "score": result["score"],
                    "strict_pass": result["strict_pass"],
                    "error": None,
                }
            )

    completed = len(runs) - infrastructure_failures
    strict_passed = sum(
        run["status"] == "completed" and run["strict_pass"] is True
        for run in runs
    )
    report = {
        "schema_version": 1,
        "suite_id": config.suite_id,
        "suite_path": str(config.suite_path),
        "runs": runs,
        "summary": {
            "total": len(runs),
            "completed": completed,
            "infrastructure_failed": infrastructure_failures,
            "strict_passed": strict_passed,
            "strict_pass": completed == len(runs) and strict_passed == len(runs),
        },
    }
    dump_json(config.result_path, report)
    return SuiteExecution(
        report=report,
        has_infrastructure_failures=bool(infrastructure_failures),
    )


def _validate_contract(value: Any) -> None:
    required = {"schema_version", "suite_id", "runs", "result_path"}
    if not isinstance(value, dict) or set(value) != required:
        raise ContractError("suite config fields do not match schema version 1")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ContractError("unsupported suite config schema_version")
    suite_id = value["suite_id"]
    if not isinstance(suite_id, str) or _IDENTIFIER.fullmatch(suite_id) is None:
        raise ContractError("suite_id must be an identifier")
    runs = value["runs"]
    if not isinstance(runs, list) or not runs:
        raise ContractError("runs must be a non-empty list")
    if any(not isinstance(run_path, str) or not run_path for run_path in runs):
        raise ContractError("runs must contain non-empty string paths")
    result_path = value["result_path"]
    if not isinstance(result_path, str) or not result_path:
        raise ContractError("result_path must be a non-empty string path")


def _resolve(root: Path, path: str) -> Path:
    try:
        if Path(path).is_absolute():
            return Path(path).resolve()
        return (root / path).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ContractError(f"cannot resolve suite path: {exc}") from exc
