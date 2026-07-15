"""Small, strict unified-diff applier for isolated candidate workspaces."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class FilePatch:
    old: str
    new: str
    hunks: list[tuple[int, list[str]]] = field(default_factory=list)


def _safe_path(root: Path, value: str) -> Path | None:
    if value == "/dev/null": return None
    relative = value.split("\t", 1)[0].removeprefix("a/").removeprefix("b/")
    target = (root / relative).resolve()
    if root.resolve() not in target.parents: raise ValueError(f"patch path escapes workspace: {value}")
    return target


def parse_unified_diff(text: str) -> list[FilePatch]:
    lines, patches, index = text.splitlines(keepends=True), [], 0
    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue
        old = lines[index][4:].rstrip("\n")
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "): raise ValueError("missing +++ file header")
        patch = FilePatch(old=old, new=lines[index][4:].rstrip("\n")); patches.append(patch); index += 1
        while index < len(lines) and not lines[index].startswith("--- "):
            match = HUNK.match(lines[index])
            if not match:
                index += 1
                continue
            start, body = int(match.group(1)), []
            index += 1
            while index < len(lines) and not lines[index].startswith(("@@ ", "--- ", "diff --git ")):
                line = lines[index]
                if line.startswith((" ", "+", "-", "\\")): body.append(line)
                index += 1
            patch.hunks.append((start, body))
    if not patches: raise ValueError("patch contains no file changes")
    return patches


def apply_unified_patch(root: Path, patch_path: Path) -> None:
    for patch in parse_unified_diff(patch_path.read_text()):
        old_path, new_path = _safe_path(root, patch.old), _safe_path(root, patch.new)
        source = [] if old_path is None else old_path.read_text().splitlines(keepends=True)
        output, cursor = [], 0
        for old_start, body in patch.hunks:
            hunk_start = old_start - 1 if old_start else 0
            if hunk_start < cursor: raise ValueError("overlapping or unordered hunks")
            output.extend(source[cursor:hunk_start]); cursor = hunk_start
            for line in body:
                if line.startswith("\\"): continue
                marker, content = line[0], line[1:]
                if marker in " -":
                    if cursor >= len(source) or source[cursor] != content:
                        found = "<eof>" if cursor >= len(source) else source[cursor].rstrip("\n")
                        raise ValueError(f"patch context mismatch: expected {content.rstrip()!r}, found {found!r}")
                    if marker == " ": output.append(source[cursor])
                    cursor += 1
                elif marker == "+": output.append(content)
        output.extend(source[cursor:])
        if new_path is None:
            if old_path is not None: old_path.unlink()
        else:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.write_text("".join(output))
            if old_path is not None and old_path != new_path and old_path.exists(): old_path.unlink()
