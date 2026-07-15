#!/usr/bin/env python3
"""Build a sanitized model-facing bundle for one repair instance."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluator.model_bundle import build_model_bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("instance", help="instance id, for example iab_0003")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    instance = ROOT / "instances" / args.instance
    output = args.output or ROOT / "bundles" / args.instance
    build_model_bundle(instance, output)
    print(output)
    return 0


if __name__ == "__main__": raise SystemExit(main())
