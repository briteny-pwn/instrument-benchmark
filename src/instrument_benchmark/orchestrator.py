from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from .agent import ClaudeCodeRunner, load_claude_code_settings
from .candidate import CandidateContract, CandidateInventory, inventory_candidate
from .contracts import (
    ContractError,
    RunConfig,
    dump_json,
    load_run_config,
    validate_visible_hashes,
)
from .environment import RepositoryPaths
from .evaluator_process import HostSourceEvaluatorRunner, SourceEvaluatorRunner
from .repository_layout import resolve_evaluator_source, resolve_instance_leaf
from .task_environment import (
    DockerTaskEnvironmentRunner,
    TaskEnvironmentHandle,
    TaskEnvironmentRunner,
)
from .workspace import prepare_workspace


def run_agent_benchmark(
    config_path: Path,
    *,
    agent: str,
    workspace_root: Path,
    instrument_checkout: Path,
    repository_paths: RepositoryPaths,
    agent_runner_factory: Callable[[], ClaudeCodeRunner] | None = None,
    task_environment_runner_factory: Callable[[], TaskEnvironmentRunner] | None = None,
    evaluator_runner_factory: Callable[[], SourceEvaluatorRunner] | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if agent != "claudecode":
        raise ContractError(f"unsupported agent: {agent}")
    config = load_run_config(config_path, repository_paths)
    instance = resolve_instance_leaf(
        config.instances_repo_path,
        config.source_id,
        config.instance_id,
    )
    evaluator = resolve_evaluator_source(
        config.evaluator_repo_path,
        config.source_id,
    )
    if instance.source_manifest.get("source_id") != evaluator.source_id:
        raise ContractError("task and evaluator source_id mismatch")
    validate_visible_hashes(instance.root, instance.manifest)
    candidate_contract = CandidateContract.from_source_manifest(
        instance.source_manifest
    )

    run_root = workspace_root.resolve() / config.run_id
    run_root.mkdir(parents=True, exist_ok=True)
    execution_root = Path(
        tempfile.mkdtemp(prefix="attempt-", dir=run_root)
    ).resolve()
    prepared = prepare_workspace(
        instance.root,
        instance.manifest,
        execution_root / "workspace",
    )
    effective_environment = dict(os.environ if environ is None else environ)
    settings = load_claude_code_settings(
        instrument_checkout,
        environ=effective_environment,
    )
    agent_runner = (
        agent_runner_factory()
        if agent_runner_factory is not None
        else ClaudeCodeRunner()
    )
    task_handle: TaskEnvironmentHandle | None = None
    task_runner: TaskEnvironmentRunner | None = None
    if candidate_contract.producer == "task_environment":
        task_runner = (
            task_environment_runner_factory()
            if task_environment_runner_factory is not None
            else DockerTaskEnvironmentRunner()
        )
        task_handle = task_runner.start(
            tasks_checkout=config.instances_repo_path,
            source_manifest=instance.source_manifest,
            instance_root=instance.root,
            instance_manifest=instance.manifest,
            run_root=execution_root,
            run_id=config.run_id,
        )
        candidate_root = task_handle.candidate_root
    else:
        candidate_root = prepared.root

    if task_handle is not None:
        effective_environment.update(task_handle.environment)
    try:
        execution = agent_runner.run(
            settings=settings,
            prompt=prepared.prompt,
            workspace=prepared.root,
            artifacts_root=execution_root / "agent",
            environ=effective_environment,
        )
    finally:
        if task_runner is not None and task_handle is not None:
            task_runner.finalize(task_handle)

    inventory = inventory_candidate(candidate_root, candidate_contract)
    request = _evaluator_request(config, instance.root, inventory)
    source_runner = (
        evaluator_runner_factory()
        if evaluator_runner_factory is not None
        else HostSourceEvaluatorRunner()
    )
    evaluator_report = source_runner.evaluate(
        evaluator_checkout=config.evaluator_repo_path,
        request=request,
        artifacts_root=execution_root / "evaluator",
    )
    _validate_source_report(evaluator_report, config)

    report = dict(evaluator_report)
    report["strict_pass"] = bool(
        inventory.complete and evaluator_report["evaluator_strict_pass"]
    )
    report["candidate_available"] = bool(inventory.files)
    report["candidate_complete"] = inventory.complete
    report["evaluated"] = True
    report["candidate"] = {
        "producer": candidate_contract.producer,
        "root": str(inventory.root),
        "files": list(inventory.files),
        "missing_files": list(inventory.missing_files),
        "invalid_files": list(inventory.invalid_files),
    }
    report["agent_execution"] = {
        **execution.to_dict(),
        "candidate_files": list(inventory.files),
        "missing_candidate_files": list(inventory.missing_files),
        "invalid_candidate_files": list(inventory.invalid_files),
    }
    report["routing"] = {
        "source_id": config.source_id,
        "task_source_manifest": str(instance.source_manifest_path),
        "evaluator_source_manifest": str(evaluator.manifest_path),
        "evaluator_entrypoint": evaluator.manifest["evaluator"]["entrypoint"],
    }
    dump_json(config.report_path, report)
    return report


def run_benchmark(
    config_path: Path,
    *,
    instrument_checkout: Path,
    repository_paths: RepositoryPaths,
) -> dict[str, Any]:
    config = load_run_config(config_path, repository_paths)
    return run_agent_benchmark(
        config_path,
        agent="claudecode",
        workspace_root=config.report_path.parent / "workspaces",
        instrument_checkout=instrument_checkout,
        repository_paths=repository_paths,
    )


def _evaluator_request(
    config: RunConfig,
    instance_root: Path,
    inventory: CandidateInventory,
) -> dict[str, Any]:
    return {
        "protocol_version": 2,
        "run_id": config.run_id,
        "source_id": config.source_id,
        "instance_id": config.instance_id,
        "instance_path": str(instance_root.resolve()),
        **inventory.to_request_fields(),
    }


def _validate_source_report(report: object, config: RunConfig) -> None:
    if not isinstance(report, dict):
        raise ContractError("source evaluator report must be an object")
    if (
        report.get("source_id") != config.source_id
        or report.get("instance_id") != config.instance_id
        or report.get("run_id") != config.run_id
        or "evaluator_id" in report
    ):
        raise ContractError("source evaluator report identity mismatch")
    score = report.get("score")
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not 0 <= float(score) <= 100
    ):
        raise ContractError("source evaluator score must be between 0 and 100")
    if not isinstance(report.get("evaluator_strict_pass"), bool):
        raise ContractError("source evaluator strict pass is invalid")
