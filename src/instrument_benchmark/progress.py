"""Run events, four-field diagnostics and read-only candidate observation."""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
from collections import deque
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, TextIO

from .candidate import CandidateContract, CandidateInventory
from .diagnostics import Redactor
from .progress_display import ProgressDisplay

STAGES = {
    "validate": "① 配置与输入检查",
    "workspace": "② 工作目录准备",
    "environment": "③ 任务环境启动",
    "agent": "④ Agent 执行",
    "cleanup": "⑤ 环境收尾",
    "candidate": "⑥ Candidate 检查",
    "evaluate": "⑦ Evaluator 评分",
    "report": "⑧ 报告保存",
}
_CURRENT: ContextVar[ProgressReporter | None] = ContextVar(
    "instrbench_progress", default=None
)


def current_progress() -> ProgressReporter | None:
    return _CURRENT.get()


def operation(
    name: str, *, logs: Sequence[Path] | None = None, **details: object
) -> None:
    progress = current_progress()
    if progress is not None:
        progress.operation(name, logs=logs, **details)


class ProgressReporter:
    def __init__(
        self,
        *,
        stream: TextIO | None = None,
        secrets: Iterable[str] = (),
        refresh_interval: float = 0.5,
    ) -> None:
        self.sanitize = Redactor(secrets)
        self.sanitize.add_environment(os.environ)
        self.display = ProgressDisplay(stream)
        self.interval = max(0.02, refresh_interval)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.total = self.finished = self.failed = self.passed = 0
        self.task = "尚未确定"
        self.stage_name = "配置加载"
        self.substep = ""
        self.logs: list[Path] = []
        self.diagnostics: list[dict[str, Any]] = []
        self.event_path: Path | None = None
        self.pending: deque[dict[str, Any]] = deque(maxlen=100)
        self.started = self.stage_started = time.monotonic()
        self.completed: set[str] = set()
        self.last_activity: float | None = None
        self.activity_text = ""
        self.tools = 0
        self.watching: tuple[Path, CandidateContract, Sequence[str]] | None = None
        self.candidate_status: dict[str, Any] = {}
        self.active = False

    def __enter__(self) -> ProgressReporter:
        self.token = _CURRENT.set(self)
        self.thread = threading.Thread(
            target=self._heartbeat, name="instrbench-progress", daemon=True
        )
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
        self.display.close()
        _CURRENT.reset(self.token)

    def start_suite(self, name: str, total: int) -> None:
        with self.lock:
            self.total = total
            self.display.start_suite(self.sanitize(name), total)

    def start_run(self, run_id: str, source_id: str, instance_id: str) -> None:
        with self.lock:
            self.task = self.sanitize(f"{source_id}/{instance_id} (run_id={run_id})")
            self.stage_name, self.substep = STAGES["validate"], ""
            self.logs, self.diagnostics = [], []
            self.event_path = None
            self.pending.clear()
            self.completed.clear()
            self.started = self.stage_started = time.monotonic()
            self.last_activity, self.activity_text, self.tools = None, "", 0
            self.watching, self.candidate_status = None, {}
            self.active = True
            self.display.start_run(self.task)
            self._event("run_started")

    def attach(self, root: Path) -> None:
        with self.lock:
            try:
                root.mkdir(parents=True, exist_ok=True)
                path = root.resolve() / "progress.jsonl"
                with path.open("a", encoding="utf-8") as handle:
                    for event in self.pending:
                        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                self.pending.clear()
                self.event_path = path
            except OSError as exc:
                self.record_error(exc)

    def identify(self, run_id: str, source_id: str, instance_id: str) -> None:
        with self.lock:
            task = self.sanitize(f"{source_id}/{instance_id} (run_id={run_id})")
            if task != self.task:
                self.task = task
                self._event("task_identified")
                self.display.message(f"任务：{task}")

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        with self.lock:
            self.stage_name, self.substep = STAGES[name], ""
            self.logs = []
            self.stage_started = time.monotonic()
            initial_errors = len(self.diagnostics)
            self._event("stage_started")
            self.display.message(f"▶ {self.stage_name}")
            self._refresh_display()
        try:
            yield
        except BaseException as exc:
            self.record_error(exc)
            raise
        else:
            with self.lock:
                self.completed.add(name)
                self._event(
                    "stage_completed",
                    duration_seconds=time.monotonic() - self.stage_started,
                )
                marker = "!" if len(self.diagnostics) > initial_errors else "✓"
                self.display.message(
                    f"{marker} {self.stage_name} [{time.monotonic() - self.stage_started:.1f}s]"
                )
                self._refresh_display()

    def operation(
        self, name: str, *, logs: Sequence[Path] | None = None, **details: object
    ) -> None:
        with self.lock:
            self.substep = self.sanitize(name)
            if logs is not None:
                self.logs = list(logs)
            self._event("operation", details=details)
            suffix = " ".join(
                f"{key}={value}" for key, value in self.sanitize.value(details).items()
            )
            self.display.message(
                f"  {self.substep}" + (f" · {suffix}" if suffix else "")
            )
            self._refresh_display()

    def activity(self, message: str, **details: object) -> None:
        with self.lock:
            self.last_activity = time.monotonic()
            self.activity_text = self.sanitize(message)[:200]
            if "tools" in details:
                self.tools = int(details["tools"])
            self._event("activity", message=self.activity_text, details=details)
            self.display.message(
                f"  {self.activity_text}"
                + (f" · 工具调用累计 {self.tools}" if "tools" in details else "")
            )
            self._refresh_display()

    def watch_candidates(
        self, root: Path, contract: CandidateContract, *, groups: Sequence[str] = ()
    ) -> None:
        with self.lock:
            self.watching = (root.resolve(), contract, tuple(groups))
            self.candidate_status = {}
            self.tick()

    def stop_watching(self) -> None:
        with self.lock:
            self.tick()
            self.watching = None

    def candidates_checked(self, inventory: CandidateInventory) -> None:
        with self.lock:
            groups = self.candidate_status.get("groups", {})
            self.candidate_status = {
                "present": len(inventory.files),
                "total": len(inventory.files)
                + len(inventory.missing_files)
                + len(inventory.invalid_files),
                "final": True,
                "groups": {
                    group: [
                        sum(path.startswith(group + "/") for path in inventory.files),
                        total,
                    ]
                    for group, (_, total) in groups.items()
                },
            }
            self._event(
                "candidate_checked",
                **self.candidate_status,
                missing_files=list(inventory.missing_files),
                invalid_files=list(inventory.invalid_files),
            )
            counts = " ".join(
                f"{g}={n}/{t}" for g, (n, t) in self.candidate_status["groups"].items()
            )
            self.display.message(
                self.sanitize(
                    f"  产物最终清单：{len(inventory.files)}/{self.candidate_status['total']} {counts}"
                )
            )
            self.tick()

    def tick(self) -> None:
        with self.lock:
            if self.watching is not None:
                root, contract, groups = self.watching
                present: list[str] = []
                for relative in contract.files:
                    path = root / relative
                    try:
                        if (
                            not path.is_symlink()
                            and path.is_file()
                            and path.resolve().is_relative_to(root)
                        ):
                            present.append(relative)
                    except (OSError, RuntimeError):
                        pass
                snapshot = {
                    "present": len(present),
                    "total": len(contract.files),
                    "groups": {
                        group: [
                            sum(p.startswith(group + "/") for p in present),
                            sum(p.startswith(group + "/") for p in contract.files),
                        ]
                        for group in groups
                    },
                }
                if snapshot != self.candidate_status:
                    self.candidate_status = snapshot
                    self._event("candidate_observed", **snapshot)
                    counts = " ".join(
                        f"{g}={n}/{t}" for g, (n, t) in snapshot["groups"].items()
                    )
                    self.display.message(
                        self.sanitize(
                            f"  产物观测（待最终校验）：{len(present)}/{len(contract.files)} {counts}"
                        )
                    )
            self._refresh_display()

    def _refresh_display(self) -> None:
        elapsed = time.monotonic() - self.stage_started
        detail = f"{self.stage_name} · {elapsed:.0f}s"
        if self.last_activity is not None and self.stage_name == STAGES["agent"]:
            detail += f" · 工具 {self.tools} · 距最近事件 {time.monotonic() - self.last_activity:.0f}s · {self.activity_text}"
        else:
            detail += f" · {self.substep}"
        if self.active:
            self.display.refresh(len(self.completed), detail, self.candidate_status)

    def record_error(
        self,
        exc: BaseException,
        *,
        logs: Sequence[Path] | None = None,
        step: str | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            previous = getattr(exc, "_instrbench_diagnostic", None)
            if previous is not None:
                return previous
            environment_diagnostic = getattr(exc, "environment_diagnostic", None)
            if environment_diagnostic is not None:
                step = step or environment_diagnostic.step
                logs = [
                    *(logs if logs is not None else self.logs),
                    *environment_diagnostic.logs,
                ]
            existing = []
            for path in [
                *(self.logs if logs is None else logs),
                *([self.event_path] if self.event_path else []),
            ]:
                try:
                    if path.is_file() and str(path.resolve()) not in existing:
                        existing.append(str(path.resolve()))
                except OSError:
                    pass
            message = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            if getattr(exc, "__notes__", None):
                message += "\n" + "\n".join(exc.__notes__)
            diagnostic = {
                "task": self.sanitize.line(self.task),
                "step": self.sanitize.line(
                    self.stage_name
                    + (f" → {step or self.substep}" if step or self.substep else "")
                ),
                "error": self.sanitize(message),
                "logs": existing,
            }
            setattr(exc, "_instrbench_diagnostic", diagnostic)
            self.diagnostics.append(diagnostic)
            self._event(
                "error",
                diagnostic=diagnostic,
                traceback="".join(traceback.format_exception(exc)),
            )
            excerpt = "\n    ".join(diagnostic["error"].splitlines()[-12:])[-2000:]
            rendered_logs = "\n      ".join(
                self.sanitize.line(path) for path in existing
            )
            self.display.message(
                self.sanitize(
                    f"任务：{diagnostic['task']}\n步骤：{diagnostic['step']}\n错误：{excerpt}\n日志："
                    + (rendered_logs if existing else "未保存")
                )
            )
            return diagnostic

    def finish_run(
        self,
        *,
        report: dict[str, Any] | None = None,
        failed: bool = False,
        interrupted: bool = False,
    ) -> None:
        with self.lock:
            self.watching = None
            self.active = False
            if not interrupted:
                self.finished += 1
            self.failed += int(failed)
            self.passed += int(bool(report and report.get("strict_pass")))
            self._event("run_finished", failed=failed, interrupted=interrupted)
            if report is not None:
                self.display.message(
                    f"任务结果：{self.task} · score={report.get('score')} · strict_pass={report.get('strict_pass')}"
                )
            self.display.finish_run(
                self.finished,
                self.total,
                f"strict_passed={self.passed}, infrastructure_failed={self.failed}",
            )

    def _event(self, event: str, **details: object) -> None:
        record = self.sanitize.value(
            {
                "event": event,
                "task": self.task,
                "step": self.stage_name,
                "operation": self.substep,
                "elapsed_seconds": round(time.monotonic() - self.started, 3),
                **details,
            }
        )
        if self.event_path is None:
            self.pending.append(record)
            return
        try:
            with self.event_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            self.event_path = None
            self.record_error(exc)

    def _heartbeat(self) -> None:
        while not self.stop.wait(self.interval):
            self.tick()
