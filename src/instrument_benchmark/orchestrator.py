from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .contracts import (
    ContractError,
    dump_json,
    load_run_config,
    load_yaml_mapping,
    repository_provenance,
    validate_dependencies,
    validate_evaluator_report,
    validate_visible_hashes,
)


def run_benchmark(
    config_path: Path,
    *,
    instrument_checkout: Path,
    allow_dirty: bool = False,
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

    with tempfile.TemporaryDirectory(prefix="instrument-orchestrator-") as directory:
        run_root = Path(directory)
        request_path = run_root / "request.json"
        evaluator_report_path = run_root / "evaluator-report.json"
        request = {
            "protocol_version": evaluator_manifest["protocol_version"],
            "run_id": config.run_id,
            "instance_id": config.instance_id,
            "instance_path": str(instance_root),
            "candidate_path": str(config.candidate_path),
            "timeout_seconds": config.timeout_seconds,
            "max_output_bytes": config.max_output_bytes,
            "repeated_worlds": config.repeated_worlds,
            "repeated_base_seed": config.repeated_base_seed,
        }
        dump_json(request_path, request)
        completed = _invoke_evaluator(
            config.evaluator_checkout,
            request_path,
            evaluator_report_path,
            timeout=config.timeout_seconds
            * (len(evaluator_manifest.get("fixed_worlds", [])) + config.repeated_worlds)
            + 30,
        )
        if completed.returncode == 2:
            raise ContractError(
                f"evaluator rejected request: {completed.stderr.strip()}"
            )
        if completed.returncode != 0:
            raise RuntimeError(
                f"evaluator infrastructure failure ({completed.returncode}): "
                f"{completed.stderr.strip()}"
            )
        try:
            raw_report = json.loads(
                evaluator_report_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"cannot load evaluator report: {exc}") from exc
        report = dict(validate_evaluator_report(raw_report))

    report["run_id"] = config.run_id
    report["provenance"] = {
        name: value.to_dict() for name, value in provenance.items()
    }
    report["orchestration"] = {
        "schema_version": 1,
        "evaluator_exit_code": 0,
    }
    dump_json(config.report_path, report)
    return report


def _invoke_evaluator(
    evaluator_checkout: Path,
    request_path: Path,
    report_path: Path,
    *,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONHASHSEED": "0",
    }
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "instrument_benchmark_evaluator.cli",
            "run",
            "--request",
            str(request_path),
            "--report",
            str(report_path),
        ],
        cwd=evaluator_checkout,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
