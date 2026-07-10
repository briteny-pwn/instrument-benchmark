"""Spec-driven grader entry point for this instance."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evaluations.common.grader_core import grade  # noqa: E402


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python grader.py path/to/solution.py")
    spec_path = Path(__file__).with_name("spec.json")
    print(json.dumps(grade(Path(sys.argv[1]).resolve(), spec_path), indent=2))

