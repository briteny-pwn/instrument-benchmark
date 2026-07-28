from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from .contracts import (
    ContractError,
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


ImageBuilderFactory = Callable[[], EvaluatorImageBuilder]
RunnerFactory = Callable[[], EvaluatorContainerRunner]


def run_benchmark(
    config_path: Path,
    *,
    instrument_checkout: Path,
    allow_dirty: bool = False,
    image_builder_factory: ImageBuilderFactory | None = None,
    runner_factory: RunnerFactory | None = None,
) -> dict[str, Any]:
    config = load_run_config(config_path)
    provenance = {
        "instrument": repository_provenance(
            instrument_checkout, allow_dirty=allow_dirty
        ),
        "instance": repository_provenance(
            config.instance_checkout, allow_dirty=allow_dirty
        ),
        "evaluator": repository_provenance(
            config.evaluator_checkout, allow_dirty=allow_dirty
        ),
    }
    instance_manifest = load_yaml_mapping(
        config.instance_checkout / config.instance_id / "instance.yaml"
        if (config.instance_checkout / config.instance_id).is_dir()
        else config.instance_checkout / "instance.yaml"
    )
    instance_root = (
        config.instance_checkout / config.instance_id
        if (config.instance_checkout / config.instance_id).is_dir()
        else config.instance_checkout
    )
    evaluator_manifest = load_yaml_mapping(
        config.evaluator_checkout / "evaluator.yaml"
    )
    if instance_manifest.get("instance_id") != config.instance_id:
        raise ContractError("configured instance_id does not match manifest")
    if evaluator_manifest.get("evaluator_id") != config.evaluator_id:
        raise ContractError("configured evaluator_id does not match manifest")
    validate_dependencies(instance_manifest, evaluator_manifest)
    validate_visible_hashes(instance_root, instance_manifest)

    assets_root = Path(__file__).resolve().parents[2] / "container"
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
    try:
        evaluator_image = image_builder.build(
            config.evaluator_checkout, run_id=config.run_id
        )
    except EvaluatorImageError as exc:
        raise EvaluatorInfrastructureError(
            f"cannot build evaluator image: {exc}"
        ) from exc

    try:
        with tempfile.TemporaryDirectory(prefix="iab-", dir="/tmp") as directory:
            run_root = Path(directory).resolve()
            # The outer evaluator runs as a fixed unprivileged UID.
            os.chmod(run_root, 0o777)
            request_path = run_root / "request.json"
            evaluator_report_path = run_root / "evaluator-report.json"
            request = {
                "protocol_version": evaluator_manifest["protocol_version"],
                "run_id": config.run_id,
                "instance_id": config.instance_id,
                "instance_path": str(instance_root),
                "candidate_path": str(config.candidate_path),
                "shared_run_root": str(run_root),
                "timeout_seconds": config.timeout_seconds,
                "max_output_bytes": config.max_output_bytes,
                "repeated_worlds": config.repeated_worlds,
                "repeated_base_seed": config.repeated_base_seed,
                "container_protocol_version": config.container_protocol_version,
                "image_mode": config.image_mode,
            }
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
                report = dict(validate_evaluator_report(container_result.report))
            except ContractError as exc:
                raise EvaluatorInfrastructureError(
                    f"evaluator produced an invalid report: {exc}"
                ) from exc
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
        "container_provenance": _container_provenance(
            instance_root, instance_manifest
        ),
    }
    dump_json(config.report_path, report)
    return report


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
