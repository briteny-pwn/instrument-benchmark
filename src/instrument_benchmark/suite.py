from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from .contracts import ContractError, RunConfig, dump_json, load_run_config
from .environment import RepositoryPaths
from .orchestrator import run_agent_benchmark
from .progress import STAGES, ProgressReporter, current_progress

_IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]*")


@dataclass(frozen=True)
class SuiteEntry:
    config_path: Path
    config: RunConfig


@dataclass(frozen=True)
class SuiteConfig:
    suite_id: str
    agent: str
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
    input_paths = {suite_path, *run_paths}
    output_paths = {result_path, *report_paths}
    collisions = input_paths & output_paths
    if collisions:
        raise ContractError(
            f"suite input/output path collision: {sorted(collisions)[0]}"
        )
    return SuiteConfig(
        suite_id=value["suite_id"],
        agent=value["agent"],
        suite_path=suite_path,
        entries=entries,
        result_path=result_path,
    )


def run_suite(
    config: SuiteConfig,
    *,
    instrument_checkout: Path,
    repository_paths: RepositoryPaths,
    benchmark_runner: BenchmarkRunner = run_agent_benchmark,
) -> SuiteExecution:
    progress = current_progress()
    if progress is None:
        with ProgressReporter():
            return run_suite(
                config,
                instrument_checkout=instrument_checkout,
                repository_paths=repository_paths,
                benchmark_runner=benchmark_runner,
            )
    progress.start_suite(config.suite_id, len(config.entries))
    runs: list[dict[str, Any]] = []
    infrastructure_failures = 0

    for index, entry in enumerate(config.entries):
        progress.start_run(
            entry.config.run_id, entry.config.source_id, entry.config.instance_id
        )
        run = {
            "index": index,
            "config_path": str(entry.config_path),
            "run_id": entry.config.run_id,
            "source_id": entry.config.source_id,
            "instance_id": entry.config.instance_id,
            "report_path": str(entry.config.report_path),
        }
        try:
            result = benchmark_runner(
                entry.config_path,
                agent=config.agent,
                workspace_root=(
                    config.result_path.parent / "workspaces" / config.suite_id
                ),
                instrument_checkout=instrument_checkout,
                repository_paths=repository_paths,
            )
        except KeyboardInterrupt as exc:
            progress.record_error(exc)
            runs.append(
                {
                    **run,
                    **getattr(exc, "_instrbench_failure_report", {}),
                    "status": "interrupted",
                    "score": None,
                    "strict_pass": None,
                    "candidate_available": False,
                    "candidate_complete": False,
                    "evaluated": False,
                    "error": "KeyboardInterrupt",
                    "diagnostics": list(progress.diagnostics),
                }
            )
            if progress.active:
                progress.finish_run(interrupted=True)
            partial = _suite_report(
                config, runs, infrastructure_failures, interrupted=True
            )
            try:
                dump_json(config.result_path, partial)
            except OSError as save_error:
                progress.record_error(save_error)
            raise
        except Exception as exc:
            progress.record_error(exc)
            infrastructure_failures += 1
            runs.append(
                {
                    **run,
                    **getattr(exc, "_instrbench_failure_report", {}),
                    "status": "infrastructure_error",
                    "score": None,
                    "strict_pass": None,
                    "candidate_available": False,
                    "candidate_complete": False,
                    "evaluated": False,
                    "error": progress.sanitize(f"{type(exc).__name__}: {exc}"),
                    "diagnostics": getattr(
                        exc, "_instrbench_diagnostics", list(progress.diagnostics)
                    ),
                    **getattr(exc, "_instrbench_candidate", {}),
                    **{
                        key: value
                        for key, value in getattr(
                            exc, "_instrbench_failure_report", {}
                        ).items()
                        if key in {"candidate_available", "candidate_complete"}
                    },
                }
            )
            if progress.active:
                progress.finish_run(failed=True)
        else:
            runs.append(
                {
                    **run,
                    "status": result.get("status", "completed"),
                    "score": result["score"],
                    "strict_pass": result["strict_pass"],
                    "candidate_available": result.get("candidate_available", True),
                    "candidate_complete": result.get("candidate_complete", True),
                    "evaluated": result.get("evaluated", True),
                    "error": None,
                    "diagnostics": result.get("diagnostics", []),
                    **{
                        key: result[key]
                        for key in ("task_environment", "candidate")
                        if key in result
                    },
                }
            )
            if progress.active:
                progress.finish_run(report=result)
        progress.stage_name = STAGES["report"]
        progress.operation("保存 Suite 汇总", logs=[], path=str(config.result_path))
        try:
            dump_json(
                config.result_path, _suite_report(config, runs, infrastructure_failures)
            )
        except OSError as exc:
            progress.record_error(exc)
            raise

    return SuiteExecution(
        report=_suite_report(config, runs, infrastructure_failures),
        has_infrastructure_failures=bool(infrastructure_failures),
    )


def _suite_report(
    config: SuiteConfig,
    runs: list[dict[str, Any]],
    infrastructure_failures: int,
    *,
    interrupted: bool = False,
) -> dict[str, Any]:

    completed = sum(
        run["status"] not in {"infrastructure_error", "interrupted"} for run in runs
    )
    strict_passed = sum(
        run["status"] == "completed" and run["strict_pass"] is True for run in runs
    )
    scored = [
        float(run["score"])
        for run in runs
        if isinstance(run["score"], (int, float)) and not isinstance(run["score"], bool)
    ]
    report = {
        "schema_version": 1,
        "suite_id": config.suite_id,
        "suite_path": str(config.suite_path),
        "runs": runs,
        "summary": {
            "total": len(config.entries),
            "completed": completed,
            "generated": sum(run["candidate_available"] is True for run in runs),
            "complete_candidates": sum(
                run["candidate_complete"] is True for run in runs
            ),
            "incomplete_candidates": sum(
                run["candidate_complete"] is False for run in runs
            ),
            "evaluated": sum(run["evaluated"] is True for run in runs),
            "infrastructure_failed": infrastructure_failures,
            "strict_passed": strict_passed,
            "mean_score": sum(scored) / len(scored) if scored else None,
            "strict_pass": completed == len(config.entries)
            and strict_passed == len(config.entries),
        },
    }
    if interrupted:
        report["interrupted"] = True
    return report


def _validate_contract(value: Any) -> None:
    required = {"suite_id", "agent", "runs", "result_path"}
    if not isinstance(value, dict) or set(value) != required:
        raise ContractError("suite config fields do not match")
    suite_id = value["suite_id"]
    if not isinstance(suite_id, str) or _IDENTIFIER.fullmatch(suite_id) is None:
        raise ContractError("suite_id must be an identifier")
    if value["agent"] != "claudecode":
        raise ContractError("suite agent must be claudecode")
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
