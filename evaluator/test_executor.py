#!/usr/bin/env python3
"""Minimal dependency-free executor for instance test functions."""

from __future__ import annotations

import importlib.util
import inspect
import json
import argparse
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    path = args.path
    spec = importlib.util.spec_from_file_location("iab_instance_test", path)
    if spec is None or spec.loader is None: raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    failures, results = 0, []
    tests = [(name, value) for name, value in vars(module).items() if name.startswith("test_") and inspect.isfunction(value)]
    for name, test in tests:
        try:
            test()
            print(f"PASS {name}")
            results.append({"name": name, "passed": True, "error": None})
        except Exception:
            failures += 1
            print(f"FAIL {name}")
            error = traceback.format_exc()
            print(error, file=sys.stderr, end="")
            results.append({"name": name, "passed": False, "error": error[-4000:]})
    print(f"{len(tests) - failures} passed, {failures} failed")
    if args.json: print("IAB_TEST_RESULTS=" + json.dumps({"tests": results}))
    return 1 if failures or not tests else 0


if __name__ == "__main__": raise SystemExit(main())
