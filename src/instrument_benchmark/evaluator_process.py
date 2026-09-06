from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from .diagnostics import Redactor
from .progress import current_progress, operation
from .streaming_process import stream_process


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
        stdout_path = artifacts_root / "evaluator-stdout.log"
        stderr_path = artifacts_root / "evaluator-stderr.log"
        operation(
            "写入评分请求", logs=[stdout_path, stderr_path], path=str(request_path)
        )
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
        progress = current_progress()
        sanitize = progress.sanitize if progress else Redactor()
        sanitize.add_environment(os.environ)
        operation("启动 Evaluator 子进程", logs=[stdout_path, stderr_path])
        completed = stream_process(
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
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            sanitize=sanitize,
            on_stdout_line=(lambda _: progress.activity("Evaluator stdout 已更新"))
            if progress
            else None,
            on_stderr_line=(lambda _: progress.activity("Evaluator stderr 已更新"))
            if progress
            else None,
        )
        if completed.returncode != 0:
            raise EvaluatorProcessError(
                f"source evaluator failed, exit_code={completed.returncode}: "
                + (completed.stderr.strip()[-2000:] or completed.stdout.strip()[-2000:])
            )
        operation("读取评分报告", path=str(report_path))
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvaluatorProcessError(
                f"source evaluator report is invalid: {exc}"
            ) from exc
        if not isinstance(report, dict):
            raise EvaluatorProcessError("source evaluator report must be an object")
        return report
