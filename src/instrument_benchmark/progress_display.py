"""tqdm rendering only; no benchmark decisions or process management."""

from __future__ import annotations

import shutil
import unicodedata
from typing import TextIO

from tqdm import tqdm


class _SafeOutput:
    """A disconnected progress sink must not terminate the benchmark."""

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self.failed = False

    def write(self, text: str) -> int:
        if not self.failed:
            try:
                self.stream.write(text)
            except (OSError, ValueError, UnicodeError):
                self.failed = True
        return len(text)

    def flush(self) -> None:
        if not self.failed:
            try:
                self.stream.flush()
            except (OSError, ValueError, UnicodeError):
                self.failed = True

    def isatty(self) -> bool:
        try:
            return not self.failed and self.stream.isatty()
        except (OSError, ValueError):
            return False

    def __getattr__(self, name: str):
        return getattr(self.stream, name)


class ProgressDisplay:
    def __init__(self, stream: TextIO | None) -> None:
        self.stream = _SafeOutput(stream) if stream is not None else None
        self.tty = bool(self.stream is not None and self.stream.isatty())
        self.suite: tqdm | None = None
        self.run: tqdm | None = None
        self.candidate: tqdm | None = None

    def _bar(self, **kwargs: object) -> tqdm:
        return tqdm(file=self.stream, dynamic_ncols=True, mininterval=0.2, **kwargs)

    def message(self, text: str) -> None:
        if self.stream is None:
            return
        try:
            if self.tty:
                tqdm.write(text, file=self.stream)
            else:
                self.stream.write(text + "\n")
                self.stream.flush()
        except (OSError, ValueError, UnicodeError):
            self.stream = None

    def start_suite(self, name: str, total: int) -> None:
        if self.tty:
            self.suite = self._bar(
                total=total,
                desc=f"Suite {name}",
                position=0,
                bar_format="{desc} |{bar}| {n_fmt}/{total_fmt} 已结束 [{elapsed}]{postfix}",
            )
        else:
            self.message(f"Suite {name}：0/{total} 已结束")

    def start_run(self, task: str) -> None:
        self.close_run()
        self.message(f"任务：{task}")
        if self.tty:
            self.run = self._bar(
                total=8,
                desc="流程节点",
                position=1 if self.suite else 0,
                leave=False,
                bar_format="{desc} {n_fmt}/8 [{elapsed}]{postfix}",
            )

    def refresh(
        self, completed: int, detail: str, candidate: dict[str, object]
    ) -> None:
        if not self.tty or self.stream is None:
            return
        try:
            if self.run is not None:
                self.run.n = completed
                width = max(12, shutil.get_terminal_size((100, 24)).columns - 28)
                clipped, used = "", 0
                for char in detail:
                    used += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
                    if used > width:
                        clipped += "…"
                        break
                    clipped += char
                self.run.set_postfix_str(clipped, refresh=True)
            if candidate:
                total = int(candidate["total"])
                if self.candidate is None:
                    self.candidate = self._bar(
                        total=total,
                        desc="产物观测（待最终校验）",
                        position=2 if self.suite else 1,
                        leave=False,
                        bar_format="{desc} |{bar}| {n_fmt}/{total_fmt}",
                    )
                self.candidate.n = int(candidate["present"])
                if candidate.get("final"):
                    self.candidate.set_description_str("产物最终清单", refresh=False)
                self.candidate.refresh()
            if self.suite is not None:
                self.suite.refresh()
        except (OSError, ValueError, UnicodeError):
            self.stream = None

    def finish_run(self, count: int, total: int, summary: str) -> None:
        self.close_run()
        if self.suite is not None:
            self.suite.n = count
            self.suite.set_postfix_str(summary, refresh=True)
        elif total:
            self.message(f"Suite：{count}/{total} 已结束，{summary}")

    def close_run(self) -> None:
        for name in ("candidate", "run"):
            bar = getattr(self, name)
            if bar is not None:
                bar.close()
                setattr(self, name, None)

    def close(self) -> None:
        self.close_run()
        if self.suite is not None:
            self.suite.close()
            self.suite = None
