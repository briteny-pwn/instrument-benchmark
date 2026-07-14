from __future__ import annotations

import ast
import builtins
import importlib.util
import json
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any


FORBIDDEN_ROOTS = {
    "avro", "bluesky", "caproto", "epics", "fastavro", "fandango", "lab_drivers",
    "ophyd", "opentrons", "pcaspy", "pyepics", "pylabrobot", "pymeasure", "pyvisa",
    "qcodes", "qcodes_contrib_drivers", "softioc", "tango", "taurus", "yaq", "yaqc",
    "yaq_traits", "yaqd_core", "yaqd_fakes",
}


def _forbidden_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        for name in names:
            if name.split(".", 1)[0] in FORBIDDEN_ROOTS:
                found.add(name)
    return sorted(found)


@contextmanager
def _blocked_imports():
    original = builtins.__import__

    def guarded(name: str, globals=None, locals=None, fromlist=(), level: int = 0):  # type: ignore[no-untyped-def]
        if level == 0 and name.split(".", 1)[0] in FORBIDDEN_ROOTS:
            raise RuntimeError(f"forbidden instrument/framework import: {name}")
        return original(name, globals, locals, fromlist, level)

    builtins.__import__ = guarded
    try:
        yield
    finally:
        builtins.__import__ = original


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    candidate = Path("/workspace/solution.py")
    output_dir = Path("/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "result.json"
    status: dict[str, Any] = {"ok": False, "forbidden_imports": []}
    try:
        forbidden = _forbidden_imports(candidate)
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
