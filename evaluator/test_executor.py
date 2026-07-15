#!/usr/bin/env python3
"""Minimal dependency-free executor for instance test functions."""

from __future__ import annotations

import importlib.util
import inspect
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))


def main() -> int:
    path = Path(sys.argv[1])
    spec = importlib.util.spec_from_file_location("iab_instance_test", path)
    if spec is None or spec.loader is None: raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    failures = 0
    tests = [(name, value) for name, value in vars(module).items() if name.startswith("test_") and inspect.isfunction(value)]
    for name, test in tests:
        try:
            test()
            print(f"PASS {name}")
        except Exception:
            failures += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"{len(tests) - failures} passed, {failures} failed")
    return 1 if failures or not tests else 0


if __name__ == "__main__": raise SystemExit(main())
