"""Run every hidden reference solution and print a compact score summary."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    failures: list[str] = []
    rows: list[tuple[str, float, bool, str]] = []
    for grader in sorted((root / "evaluations").glob("*/*/grader.py")):
        reference = grader.parent / "reference_solution/experiment.py"
        if not reference.exists():
            continue
        process = subprocess.run(
            [sys.executable, str(grader), str(reference)],
            cwd=root,
            text=True,
            capture_output=True,
        )
        instance_id = grader.parent.name
        if process.returncode != 0:
            failures.append(f"{instance_id}: grader exited {process.returncode}: {process.stderr.strip()}")
            rows.append((instance_id, 0.0, False, "error"))
            continue
        try:
            report = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            failures.append(f"{instance_id}: invalid JSON report: {exc}")
            rows.append((instance_id, 0.0, False, "invalid-json"))
            continue
        total = float(report.get("total", 0.0))
        passed = bool(report.get("pass"))
        mode = str(report.get("evaluation_mode", "single"))
        rows.append((instance_id, total, passed, mode))
        if not passed or total != 1.0:
            failures.append(f"{instance_id}: expected reference total=1.0 and pass=true, got {total} / {passed}")

    width = max((len(row[0]) for row in rows), default=8)
    for instance_id, total, passed, mode in rows:
        print(f"{instance_id:<{width}}  total={total:.4f}  pass={str(passed).lower():5}  mode={mode}")
    if failures:
        print("\nReference suite failures:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        raise SystemExit(1)
    print(f"\nAll {len(rows)} reference solutions passed.")


if __name__ == "__main__":
    main()
