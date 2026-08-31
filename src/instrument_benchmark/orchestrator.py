from __future__ import annotations

import os
import hashlib
import json
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from .contracts import (
    ContractError,
    RunConfig,
    dump_json,
    load_run_config,
    load_yaml_mapping,
    repository_provenance,
    validate_dependencies,
    validate_evaluator_report,
    validate_evaluator_container_evidence,
    validate_visible_hashes,
)
from .evaluator_image import EvaluatorImageBuilder, EvaluatorImageError
from .evaluator_runtime import (
    EvaluatorContainerRunner,
    EvaluatorInfrastructureError,
)
from .environment import RepositoryPaths
from .repository_layout import resolve_evaluator_leaf, resolve_instance_leaf


ImageBuilderFactory = Callable[[], EvaluatorImageBuilder]
RunnerFactory = Callable[[], EvaluatorContainerRunner]


def run_benchmark(
    config_path: Path,
    *,
    instrument_checkout: Path,
    repository_paths: RepositoryPaths,
    allow_dirty: bool = False,
    image_builder_factory: ImageBuilderFactory | None = None,
    runner_factory: RunnerFactory | None = None,
) -> dict[str, Any]:
    config = load_run_config(config_path, repository_paths)
    instance_leaf = resolve_instance_leaf(
        config.instances_repo_path, config.source_id, config.instance_id
    )
    evaluator_leaf = resolve_evaluator_leaf(
        config.evaluator_repo_path, config.source_id, config.evaluator_id
    )
    instance_root = instance_leaf.root
    instance_manifest = instance_leaf.manifest
    evaluator_manifest = evaluator_leaf.manifest
    validate_dependencies(config.source_id, instance_manifest, evaluator_manifest)
    validate_visible_hashes(instance_root, instance_manifest)
    provenance = {
        "instrument": repository_provenance(
            instrument_checkout, allow_dirty=allow_dirty
        ),
        "instance": repository_provenance(
            config.instances_repo_path, allow_dirty=allow_dirty
        ),
        "evaluator": repository_provenance(
            config.evaluator_repo_path, allow_dirty=allow_dirty
        ),
    }
    if config.openfibsem_checkout is not None:
        provenance["openfibsem"] = repository_provenance(
            config.openfibsem_checkout,
            allow_dirty=allow_dirty,
            include_untracked=False,
        )
    is_fibsem = (
        config.source_id == "openfibsem"
        and config.evaluator_id == "fibsem_liftout_v1"
    )
    if is_fibsem and (
        evaluator_manifest.get("openfibsem_commit") != config.openfibsem_commit
    ):
        raise ContractError("configured OpenFIBSEM commit does not match evaluator")

    assets_root = config.evaluator_repo_path / "container"
    image_builder = (
        image_builder_factory()
        if image_builder_factory is not None
        else EvaluatorImageBuilder(assets_root=assets_root)
    )
    runner = (
        runner_factory()
        if runner_factory is not None
        else EvaluatorContainerRunner()
    )
    published_artifacts: dict[str, Any] | None = None
    try:
        build_arguments: dict[str, Any] = {}
        if is_fibsem:
            build_arguments = {
                "openfibsem_checkout": config.openfibsem_checkout,
                "openfibsem_commit": config.openfibsem_commit,
            }
        evaluator_image = image_builder.build(
            config.evaluator_repo_path,
            run_id=config.run_id,
            source_id=config.source_id,
            evaluator_id=config.evaluator_id,
            **build_arguments,
        )
    except EvaluatorImageError as exc:
        raise EvaluatorInfrastructureError(
            f"cannot build evaluator image: {exc}"
        ) from exc

    try:
        if (
            evaluator_image.source_id != config.source_id
            or evaluator_image.evaluator_id != config.evaluator_id
        ):
            raise EvaluatorInfrastructureError(
                "evaluator image source identity does not match this run"
            )
        with tempfile.TemporaryDirectory(prefix="iab-", dir="/tmp") as directory:
            run_root = Path(directory).resolve()
            # The outer evaluator runs as a fixed unprivileged UID.
            os.chmod(run_root, 0o777)
            request_path = run_root / "request.json"
            evaluator_report_path = run_root / "evaluator-report.json"
            request = _build_evaluator_request(
                config,
                instance_root=instance_root,
                shared_run_root=run_root,
                evaluator_manifest=evaluator_manifest,
                evaluator_image_id=evaluator_image.image_id,
            )
            dump_json(request_path, request)
            container_result = runner.run(
                image=evaluator_image,
                request_path=request_path,
                report_path=evaluator_report_path,
                instance_path=instance_root,
                candidate_path=config.candidate_path,
                shared_run_root=run_root,
                run_id=config.run_id,
                timeout=config.timeout_seconds
                * (
                    len(evaluator_manifest.get("fixed_worlds", []))
                    + config.repeated_worlds
                )
                + 60,
                stdout_limit=max(config.max_output_bytes, 64 * 1024),
                stderr_limit=max(config.max_output_bytes, 64 * 1024),
            )
            try:
                report = dict(
                    validate_evaluator_report(
                        container_result.report,
                        config.source_id,
                        config.evaluator_id,
                        expected_run_id=config.run_id,
                    )
                )
            except ContractError as exc:
                raise EvaluatorInfrastructureError(
                    f"evaluator produced an invalid report: {exc}"
                ) from exc
            if is_fibsem:
                _validate_fibsem_run_binding(
                    report,
                    config=config,
                    evaluator_image=evaluator_image,
                    instance_root=instance_root,
                    instance_manifest=instance_manifest,
                )
                published_artifacts = _publish_fibsem_artifacts(
                    run_root,
                    report,
                    config.report_path.with_suffix(".artifacts"),
                    run_id=config.run_id,
                )
    finally:
        primary_error = sys.exception()
        remove = getattr(image_builder, "remove", None)
        if callable(remove):
            try:
                remove(evaluator_image)
            except Exception as cleanup_error:
                if primary_error is not None:
                    primary_error.add_note(
                        f"failed to remove evaluator image tag: {cleanup_error}"
                    )
                else:
                    raise EvaluatorInfrastructureError(
                        f"failed to remove evaluator image tag: {cleanup_error}"
                    ) from cleanup_error

    report["run_id"] = config.run_id
    report["source_id"] = config.source_id
    report["instance_id"] = config.instance_id
    report["evaluator_id"] = config.evaluator_id
    report["provenance"] = {
        name: value.to_dict() for name, value in provenance.items()
    }
    outer_evidence = validate_evaluator_container_evidence(
        container_result.evidence.to_dict()
    )
    report["orchestration"] = {
        "schema_version": 1,
        "evaluator_exit_code": container_result.evidence.exit_code,
        "evaluator_container": outer_evidence,
        "evaluator_image": {
            "reference": evaluator_image.reference,
            "image_id": evaluator_image.image_id,
            "repo_digest": evaluator_image.repo_digest,
            "dockerfile_sha256": evaluator_image.dockerfile_sha256,
            "build_manifest_sha256": evaluator_image.build_manifest_sha256,
            "evaluator_commit": evaluator_image.evaluator_commit,
            "source_id": evaluator_image.source_id,
            "evaluator_id": evaluator_image.evaluator_id,
            "source_manifest_sha256": evaluator_image.source_manifest_sha256,
            "source_tree_sha256": evaluator_image.source_tree_sha256,
            "openfibsem_commit": getattr(
                evaluator_image, "openfibsem_commit", None
            ),
            "openfibsem_source_sha256": (
                getattr(evaluator_image, "openfibsem_source_sha256", None)
            ),
        },
        "container_provenance": _container_provenance(
            instance_root, instance_manifest
        ),
    }
    if published_artifacts is not None:
        report["artifacts"] = published_artifacts
    dump_json(config.report_path, report)
    return report


def _build_evaluator_request(
    config: RunConfig,
    *,
    instance_root: Path,
    shared_run_root: Path,
    evaluator_manifest: dict[str, Any],
    evaluator_image_id: str,
) -> dict[str, Any]:
    request = {
        "protocol_version": 2,
        "run_id": config.run_id,
        "source_id": config.source_id,
        "instance_id": config.instance_id,
        "evaluator_id": config.evaluator_id,
        "instance_path": str(instance_root),
        "candidate_path": str(config.candidate_path),
        "shared_run_root": str(shared_run_root),
        "timeout_seconds": config.timeout_seconds,
        "max_output_bytes": config.max_output_bytes,
        "repeated_worlds": config.repeated_worlds,
        "repeated_base_seed": config.repeated_base_seed,
        "container_protocol_version": config.container_protocol_version,
        "image_mode": config.image_mode,
    }
    if (config.source_id, config.evaluator_id) in {
        ("pyvisa", "pyvisa_dut_validation_v2"),
        ("openfibsem", "fibsem_liftout_v1"),
    }:
        digest = evaluator_image_id.removeprefix("sha256:")
        if (
            not evaluator_image_id.startswith("sha256:")
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ContractError("sibling evaluator image ID must be exact")
        request["evaluator_image_id"] = evaluator_image_id
    return request


def _container_provenance(
    instance_root: Path, instance_manifest: dict[str, Any]
) -> dict[str, Any]:
    container = instance_manifest.get("container")
    if not isinstance(container, dict):
        raise ContractError("instance container contract is missing")
    lock_name = container.get("lock_file")
    if not isinstance(lock_name, str):
        raise ContractError("instance image lock path is missing")
    lock = load_yaml_mapping(instance_root / lock_name)
    built = lock.get("built_image")
    if not isinstance(built, dict):
        raise ContractError("instance built image lock is missing")
    completed = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RuntimeError(
            "cannot record Docker Engine version: "
            f"{completed.stderr.strip() or 'unknown error'}"
        )
    return {
        "container_protocol_version": container.get("protocol_version"),
        "image_mode": "locked",
        "dockerfile_sha256": lock.get("dockerfile_sha256"),
        "image_digest": built.get("digest"),
        "docker_engine_version": completed.stdout.strip(),
    }


def _publish_fibsem_artifacts(
    run_root: Path,
    report: dict[str, Any],
    destination: Path,
    *,
    run_id: str,
) -> dict[str, Any]:
    run_root = run_root.resolve()
    destination = destination.resolve()
    if destination.exists() or destination.is_symlink():
        raise EvaluatorInfrastructureError(
            f"FIBSEM artifact destination already exists: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    summaries: dict[str, list[Path]] = {}
    for path in run_root.glob("fibsem-w-*/evidence/service-summary.json"):
        resolved = path.resolve()
        if path.is_symlink() or not resolved.is_relative_to(run_root):
            raise EvaluatorInfrastructureError("FIBSEM evidence path escapes run root")
        summary = _read_json_object(resolved, "FIBSEM service summary")
        world_id = summary.get("world_id")
        if not isinstance(world_id, str):
            raise EvaluatorInfrastructureError(
                "FIBSEM service summary world identity is invalid"
            )
        summaries.setdefault(world_id, []).append(resolved)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
    )
    published: dict[str, dict[str, dict[str, str]]] = {}
    try:
        worlds = report.get("worlds")
        if not isinstance(worlds, list):
            raise EvaluatorInfrastructureError("FIBSEM report worlds are invalid")
        report_world_ids = {
            world.get("world_id") for world in worlds if isinstance(world, dict)
        }
        if set(summaries) - report_world_ids:
            raise EvaluatorInfrastructureError(
                "FIBSEM evidence contains an undeclared world"
            )
        for world in worlds:
            if not isinstance(world, dict) or not isinstance(
                world.get("world_id"), str
            ):
                raise EvaluatorInfrastructureError(
                    "FIBSEM report world identity is invalid"
                )
            world_id = world["world_id"]
            matches = summaries.get(world_id, [])
            if len(matches) != 1:
                if world.get("retry_eligible") and not matches:
                    published[world_id] = {}
                    continue
                raise EvaluatorInfrastructureError(
                    f"FIBSEM trusted evidence count is invalid: {world_id}"
                )
            summary_path = matches[0]
            evidence_root = summary_path.parent
            summary = _read_json_object(summary_path, "FIBSEM service summary")
            checkpoints = world.get("checkpoints")
            checkpoint_ids = list(checkpoints) if isinstance(checkpoints, dict) else []
            if (
                summary.get("run_id") != run_id
                or summary.get("world_id") != world_id
                or summary.get("checkpoints") != checkpoint_ids
            ):
                raise EvaluatorInfrastructureError(
                    f"FIBSEM service summary disagrees with report: {world_id}"
                )
            world_destination = temporary / world_id
            world_destination.mkdir()
            for filename in (
                "service-summary.json",
                "journal.jsonl",
                "journal-summary.json",
            ):
                _copy_regular_file(
                    evidence_root / filename,
                    world_destination / filename,
                )
            step_records: dict[str, dict[str, str]] = {}
            for step_id in checkpoint_ids:
                checkpoint = checkpoints[step_id]
                source = evidence_root / "artifacts" / world_id / step_id
                expected = checkpoint.get("artifact_digest")
                if not isinstance(expected, str) or _bundle_digest(source) != expected:
                    raise EvaluatorInfrastructureError(
                        f"FIBSEM artifact digest mismatch: {world_id}/{step_id}"
                    )
                target = world_destination / step_id
                _copy_regular_tree(source, target)
                if _bundle_digest(target) != expected:
                    raise EvaluatorInfrastructureError(
                        f"published FIBSEM artifact changed: {world_id}/{step_id}"
                    )
                step_records[step_id] = {
                    "path": f"{world_id}/{step_id}",
                    "sha256": expected,
                }
            published[world_id] = step_records
            _make_read_only(world_destination)
        os.replace(temporary, destination)
        _make_read_only(destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {"root": destination.name, "worlds": published}


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluatorInfrastructureError(f"cannot read {label}: {exc}") from exc
    if len(payload) > 4 * 1024 * 1024 or not isinstance(value, dict):
        raise EvaluatorInfrastructureError(f"{label} is invalid")
    return value


def _bundle_digest(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise EvaluatorInfrastructureError("FIBSEM checkpoint bundle is invalid")
    records: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        payload = _regular_payload(path, relative)
        records[relative] = hashlib.sha256(payload).hexdigest()
    if "checkpoint.json" not in records or not records:
        raise EvaluatorInfrastructureError("FIBSEM checkpoint bundle is incomplete")
    return hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _copy_regular_tree(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise EvaluatorInfrastructureError("FIBSEM artifact source is invalid")
    destination.mkdir()
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir() and not path.is_symlink():
            target.mkdir(exist_ok=True)
            continue
        _copy_regular_file(path, target)


def _copy_regular_file(source: Path, destination: Path) -> None:
    payload = _regular_payload(source, source.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    destination.chmod(0o444)


def _regular_payload(path: Path, label: str) -> bytes:
    try:
        info = path.lstat()
    except OSError as exc:
        raise EvaluatorInfrastructureError(
            f"cannot inspect FIBSEM artifact {label}: {exc}"
        ) from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_size <= 0
        or info.st_size > 64 * 1024 * 1024
    ):
        raise EvaluatorInfrastructureError(f"FIBSEM artifact file is invalid: {label}")
    return path.read_bytes()


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir():
            path.chmod(0o555)
        else:
            path.chmod(0o444)
    root.chmod(0o555)


def _validate_fibsem_run_binding(
    report: dict[str, Any],
    *,
    config: RunConfig,
    evaluator_image: object,
    instance_root: Path,
    instance_manifest: dict[str, Any],
) -> None:
    if (
        report.get("openfibsem_commit") != config.openfibsem_commit
        or getattr(evaluator_image, "openfibsem_commit", None)
        != config.openfibsem_commit
        or not isinstance(
            getattr(evaluator_image, "openfibsem_source_sha256", None), str
        )
    ):
        raise EvaluatorInfrastructureError(
            "FIBSEM evaluator/OpenFIBSEM provenance does not match this run"
        )
    image_id = getattr(evaluator_image, "image_id", None)
    lock_name = instance_manifest.get("container", {}).get("lock_file")
    if not isinstance(lock_name, str):
        raise EvaluatorInfrastructureError("FIBSEM candidate image lock is missing")
    lock = load_yaml_mapping(instance_root / lock_name)
    candidate_digest = lock.get("built_image", {}).get("digest")
    if not isinstance(image_id, str) or not isinstance(candidate_digest, str):
        raise EvaluatorInfrastructureError("FIBSEM image identities are invalid")
    for world in report["worlds"]:
        candidate = world.get("candidate_container_evidence")
        sim = world.get("sim_container_evidence")
        if candidate is not None and candidate.get("image_digest") != candidate_digest:
            raise EvaluatorInfrastructureError(
                f"FIBSEM candidate image mismatch: {world['world_id']}"
            )
        if sim is not None and sim.get("image_digest") != image_id:
            raise EvaluatorInfrastructureError(
                f"FIBSEM simulator image mismatch: {world['world_id']}"
            )
