from __future__ import annotations

import builtins
import importlib
import importlib.util
import json
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from forbidden_imports import FORBIDDEN_IMPORT_ROOTS, check_candidate_imports


@contextmanager
def _blocked_imports():
    original_import = builtins.__import__
    original_import_module = importlib.import_module

    def guarded(name: str, globals=None, locals=None, fromlist=(), level: int = 0):  # type: ignore[no-untyped-def]
        if level == 0 and name.split(".", 1)[0] in FORBIDDEN_IMPORT_ROOTS:
            raise RuntimeError(f"forbidden instrument/framework import: {name}")
        return original_import(name, globals, locals, fromlist, level)

    def guarded_import_module(name: str, package: str | None = None):
        if name.split(".", 1)[0] in FORBIDDEN_IMPORT_ROOTS:
            raise RuntimeError(f"forbidden instrument/framework import: {name}")
        return original_import_module(name, package)

    builtins.__import__ = guarded
    importlib.import_module = guarded_import_module
    try:
        yield
    finally:
        builtins.__import__ = original_import
        importlib.import_module = original_import_module


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    candidate = Path("/workspace/solution.py")
    output_dir = Path("/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "result.json"
    status: dict[str, Any] = {"ok": False, "forbidden_imports": []}
    try:
        forbidden = check_candidate_imports(candidate)
        status["forbidden_imports"] = forbidden
        if forbidden:
            raise RuntimeError("candidate imports forbidden instrument/framework modules")
        module_spec = importlib.util.spec_from_file_location("candidate_solution", candidate)
        if module_spec is None or module_spec.loader is None:
            raise RuntimeError("cannot load solution.py")
        module = importlib.util.module_from_spec(module_spec)
        with _blocked_imports():
            module_spec.loader.exec_module(module)
            if not hasattr(module, "run_experiment"):
                raise RuntimeError("solution.py must expose run_experiment(output_path)")
            returned = module.run_experiment(str(result_path))
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
        elif isinstance(returned, dict):
            result = returned
            _write(result_path, result)
        else:
            raise RuntimeError("run_experiment returned no dictionary and wrote no JSON result")
        if not isinstance(result, dict):
            raise RuntimeError("experiment result must be a JSON object")
        status["ok"] = True
    except BaseException as exc:
        status["error"] = f"{type(exc).__name__}: {exc}"
        status["traceback"] = traceback.format_exc()
    _write(output_dir / "execution.json", status)
    raise SystemExit(0 if status["ok"] else 1)


if __name__ == "__main__":
    main()
