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
from .evaluator_process import (
    EvaluatorProcessError,
    HostSourceEvaluatorRunner,
    SourceEvaluatorRunner,
)
from .progress import ProgressReporter, current_progress
from .repository_layout import resolve_evaluator_source, resolve_instance_leaf
from .task_environment import (
    DockerTaskEnvironmentRunner,
    TaskEnvironmentError,
    TaskEnvironmentHandle,
    TaskEnvironmentRunner,
)
from .task_environment_status import TaskEnvironmentResult
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
    progress = current_progress()
    if progress is None:
        with ProgressReporter():
            return run_agent_benchmark(
                config_path,
                agent=agent,
                workspace_root=workspace_root,
                instrument_checkout=instrument_checkout,
                repository_paths=repository_paths,
                agent_runner_factory=agent_runner_factory,
                task_environment_runner_factory=task_environment_runner_factory,
                evaluator_runner_factory=evaluator_runner_factory,
                environ=environ,
            )
    if not progress.active:
        progress.start_run(config_path.stem, "未加载", "未加载")
    inventory: CandidateInventory | None = None
    config: RunConfig | None = None
    candidate_root: Path | None = None
    candidate_contract: CandidateContract | None = None
    environment_result: TaskEnvironmentResult | None = None
    task_runner: TaskEnvironmentRunner | None = None
    execution = None
    try:
        with progress.stage("validate"):
            progress.operation("加载运行配置", config=str(config_path.resolve()))
            if agent != "claudecode":
                raise ContractError(f"unsupported agent: {agent}")
            config = load_run_config(config_path, repository_paths)
            progress.identify(config.run_id, config.source_id, config.instance_id)
            progress.operation(
                "匹配 Tasks source 与 instance",
                source=config.source_id,
                instance=config.instance_id,
            )
            instance = resolve_instance_leaf(
                config.instances_repo_path, config.source_id, config.instance_id
            )
            progress.operation("匹配 Evaluator source", source=config.source_id)
            evaluator = resolve_evaluator_source(
                config.evaluator_repo_path, config.source_id
            )
            if instance.source_manifest.get("source_id") != evaluator.source_id:
                raise ContractError("task and evaluator source_id mismatch")
            progress.operation("校验可见文件哈希")
            validate_visible_hashes(instance.root, instance.manifest)
            candidate_contract = CandidateContract.from_source_manifest(
                instance.source_manifest
            )
            effective_environment = dict(os.environ if environ is None else environ)
            progress.sanitize.add_environment(effective_environment)
            progress.operation("加载 Agent 环境配置")
            settings = load_claude_code_settings(
                instrument_checkout, environ=effective_environment
            )
            progress.sanitize.add_environment(settings.environment)
        with progress.stage("workspace"):
            progress.operation("创建本次运行目录")
            run_root = workspace_root.resolve() / config.run_id
            run_root.mkdir(parents=True, exist_ok=True)
            execution_root = Path(
                tempfile.mkdtemp(prefix="attempt-", dir=run_root)
            ).resolve()
            progress.attach(execution_root)
            prepared = prepare_workspace(
                instance.root, instance.manifest, execution_root / "workspace"
            )
            progress.operation("工作目录已准备", cwd=str(prepared.root))
        agent_runner = (
            agent_runner_factory() if agent_runner_factory else ClaudeCodeRunner()
        )
        task_handle: TaskEnvironmentHandle | None = None
        task_runner: TaskEnvironmentRunner | None = None
        with progress.stage("environment"):
            if candidate_contract.producer == "task_environment":
                task_runner = (
                    task_environment_runner_factory()
                    if task_environment_runner_factory
                    else DockerTaskEnvironmentRunner()
                )
                candidate_root = execution_root / "candidate"
                task_handle = task_runner.start(
                    tasks_checkout=config.instances_repo_path,
                    source_manifest=instance.source_manifest,
                    instance_root=instance.root,
                    instance_manifest=instance.manifest,
                    run_root=execution_root,
                    run_id=config.run_id,
                )
                candidate_root = task_handle.candidate_root
                effective_environment.update(task_handle.environment)
            else:
                progress.operation("跳过：该 source 由 Agent 生成文件")
                candidate_root = prepared.root
        primary: BaseException | None = None
        try:
            with progress.stage("agent"):
                progress.watch_candidates(
                    candidate_root,
                    candidate_contract,
                    groups=instance.source_manifest["candidate"].get("groups", ()),
                )
                progress.operation("运行 Claude Code", model=settings.model)
                execution = agent_runner.run(
                    settings=settings,
                    prompt=prepared.prompt,
                    workspace=prepared.root,
                    artifacts_root=execution_root / "agent",
                    environ=effective_environment,
                    **(
                        {"on_poll": lambda: task_runner.check_health(task_handle)}
                        if task_runner is not None and task_handle is not None
                        else {}
                    ),
                )
                if execution.status != "completed":
                    progress.record_error(
                        RuntimeError(
                            f"Agent {execution.status}, "
                            f"exit_code={execution.exit_code}, "
                            f"duration={execution.duration_seconds:.1f}s"
                            + (
                                f": {execution.error_message}"
                                if execution.error_message
                                else ""
                            )
                        ),
                        logs=[execution.stdout_path, execution.stderr_path],
                    )
        except BaseException as exc:
            primary = exc
            raise
        finally:
            progress.stop_watching()
            try:
                with progress.stage("cleanup"):
                    if task_runner is not None and task_handle is not None:
                        environment_result = task_runner.finalize(task_handle)
                        if not isinstance(environment_result, TaskEnvironmentResult):
                            raise TaskEnvironmentError(
                                "task environment returned no valid terminal result"
                            )
                        if environment_result.status not in {
                            "completed",
                            "candidate_incomplete",
                            "candidate_failure",
                        }:
                            diagnostic = next(
                                iter(environment_result.diagnostics), None
                            )
                            raise TaskEnvironmentError(
                                f"{diagnostic.error_type}: {diagnostic.error}"
                                if diagnostic
                                else f"task environment ended with {environment_result.status}",
                                diagnostic=diagnostic,
                            )
                    else:
                        progress.operation("无任务容器需要收尾")
            except BaseException as cleanup_error:
                environment_result = getattr(
                    task_runner, "last_result", environment_result
                )
                if primary is None or isinstance(cleanup_error, KeyboardInterrupt):
                    raise
                primary.add_note(f"task environment finalization: {cleanup_error}")
        with progress.stage("candidate"):
            inventory = inventory_candidate(candidate_root, candidate_contract)
            progress.candidates_checked(inventory)
            progress.operation(
                "文件清单检查完成",
                checked=len(candidate_contract.files),
                present=len(inventory.files),
                missing=len(inventory.missing_files),
                invalid=len(inventory.invalid_files),
            )
            if not inventory.complete:
                progress.record_error(
                    ValueError(
                        "candidate incomplete: "
                        f"missing={list(inventory.missing_files)}, "
                        f"invalid={list(inventory.invalid_files)}"
                    )
                )
        with progress.stage("evaluate"):
            request = _evaluator_request(config, instance.root, inventory)
            source_runner = (
                evaluator_runner_factory()
                if evaluator_runner_factory
                else HostSourceEvaluatorRunner()
            )
            progress.operation(
                "运行 source evaluator",
                entrypoint=evaluator.manifest["evaluator"]["entrypoint"],
            )
            evaluator_report = source_runner.evaluate(
                evaluator_checkout=config.evaluator_repo_path,
                request=request,
                artifacts_root=execution_root / "evaluator",
            )
            progress.operation("校验评分报告")
            try:
                _validate_source_report(evaluator_report, config)
            except ContractError as exc:
                raise EvaluatorProcessError(str(exc)) from exc
        with progress.stage("report"):
            report = dict(evaluator_report)
            report["strict_pass"] = bool(
                inventory.complete and evaluator_report["evaluator_strict_pass"]
            )
            report.update(
                candidate_available=bool(inventory.files),
                candidate_complete=inventory.complete,
                evaluated=True,
            )
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
            report["diagnostics"] = list(progress.diagnostics)
            if environment_result is not None:
                report["task_environment"] = progress.sanitize.value(
                    environment_result.to_dict()
                )
            progress.operation("保存单任务报告", path=str(config.report_path))
            dump_json(config.report_path, report)
    except BaseException as exc:
        environment_result = environment_result or getattr(
            task_runner, "last_result", None
        )
        if (
            inventory is None
            and candidate_root is not None
            and candidate_contract is not None
        ):
            try:
                inventory = inventory_candidate(candidate_root, candidate_contract)
            except Exception as inventory_error:
                exc.add_note(f"candidate inventory: {inventory_error}")
        progress.record_error(exc)
        if config is not None:
            failure = {
                "run_id": config.run_id,
                "source_id": config.source_id,
                "instance_id": config.instance_id,
                "status": "interrupted"
                if isinstance(exc, KeyboardInterrupt)
                else "infrastructure_error",
                "score": None,
                "strict_pass": None,
                "evaluated": False,
                "candidate_available": bool(inventory and inventory.files),
                "candidate_complete": bool(inventory and inventory.complete),
                "error": progress.sanitize(f"{type(exc).__name__}: {exc}"),
                "diagnostics": list(progress.diagnostics),
            }
            if inventory is not None:
                failure["candidate"] = {
                    "producer": candidate_contract.producer,
                    "root": str(inventory.root),
                    "files": list(inventory.files),
                    "missing_files": list(inventory.missing_files),
                    "invalid_files": list(inventory.invalid_files),
                }
            if environment_result is not None:
                failure["task_environment"] = progress.sanitize.value(
                    environment_result.to_dict()
                )
            if execution is not None:
                failure["agent_execution"] = progress.sanitize.value(
                    execution.to_dict()
                )
            setattr(exc, "_instrbench_failure_report", failure)
            try:
                dump_json(config.report_path, failure)
            except OSError as save_error:
                exc.add_note(f"cannot persist failure report: {save_error}")
                progress.record_error(save_error)
        setattr(exc, "_instrbench_diagnostics", list(progress.diagnostics))
        if inventory is not None:
            setattr(
                exc,
                "_instrbench_candidate",
                {
                    "candidate_available": bool(inventory.files),
                    "candidate_complete": inventory.complete,
                },
            )
        progress.finish_run(
            failed=not isinstance(exc, KeyboardInterrupt),
            interrupted=isinstance(exc, KeyboardInterrupt),
        )
        raise
    progress.finish_run(report=report)
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
