#!/usr/bin/env python3
"""Score a JSON list or JSONL candidate file."""

from __future__ import annotations

import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iab.scoring import hard_filter_reasons, score_candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=Path("data/scored_candidates.json"))
    args = parser.parse_args()
    raw = args.input.read_text(encoding="utf-8")
    candidates = json.loads(raw) if raw.lstrip().startswith("[") else [json.loads(line) for line in raw.splitlines() if line.strip()]
    result = []
    for candidate in candidates:
        reasons = hard_filter_reasons(candidate)
        scored = score_candidate(candidate)
        if reasons: scored.update(grade="drop", hard_filter_reasons=reasons)
        result.append(scored)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"total": len(result), "kept": sum(x["grade"] != "drop" for x in result), "output": str(args.output)}))
    return 0


if __name__ == "__main__": raise SystemExit(main())
