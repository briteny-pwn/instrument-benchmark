from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol


class EvaluatorProcessError(RuntimeError):
    """The source evaluator process failed or returned no report."""


class SourceEvaluatorRunner(Protocol):
    def evaluate(
        self,
        *,
        evaluator_checkout: Path,
        request: Mapping[str, Any],
        artifacts_root: Path,
    ) -> dict[str, Any]: ...


class HostSourceEvaluatorRunner:
    def evaluate(
        self,
        *,
        evaluator_checkout: Path,
        request: Mapping[str, Any],
        artifacts_root: Path,
    ) -> dict[str, Any]:
        artifacts_root.mkdir(parents=True, exist_ok=True)
        request_path = artifacts_root / "evaluator-request.json"
        report_path = artifacts_root / "evaluator-report.json"
        request_path.write_text(
            json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        environment = dict(os.environ)
        for name in (
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
            "INSTRBENCH_AGENT_MODEL",
        ):
            environment.pop(name, None)
        pythonpath = [str(evaluator_checkout.resolve())]
        vendor = evaluator_checkout / "vendor/pyvisa-sim-iab"
        if vendor.is_dir():
            pythonpath.append(str(vendor.resolve()))
        if environment.get("PYTHONPATH"):
            pythonpath.append(environment["PYTHONPATH"])
        environment["PYTHONPATH"] = os.pathsep.join(pythonpath)
        completed = subprocess.run(
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
            cwd=evaluator_checkout.resolve(),
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        (artifacts_root / "evaluator-stdout.log").write_text(
            completed.stdout, encoding="utf-8"
        )
        (artifacts_root / "evaluator-stderr.log").write_text(
            completed.stderr, encoding="utf-8"
        )
        if completed.returncode != 0:
            raise EvaluatorProcessError(
                "source evaluator failed: "
                + (completed.stderr.strip() or f"exit {completed.returncode}")
            )
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvaluatorProcessError(f"source evaluator report is invalid: {exc}") from exc
        if not isinstance(report, dict):
            raise EvaluatorProcessError("source evaluator report must be an object")
        return report
