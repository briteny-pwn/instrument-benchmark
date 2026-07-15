"""Single source of truth for candidate import restrictions."""

from __future__ import annotations

import ast
from pathlib import Path


FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "PyTango",
        "avro",
        "bluesky",
        "caproto",
        "epics",
        "evaluations",
        "fastavro",
        "fandango",
        "lab_drivers",
        "ophyd",
        "opentrons",
        "pcaspy",
        "pyepics",
        "pylabrobot",
        "pymeasure",
        "pytango",
        "pyvisa",
        "qcodes",
        "qcodes_contrib_drivers",
        "sardana",
        "softioc",
        "tango",
        "taurus",
        "yaq",
        "yaq_traits",
        "yaqc",
        "yaqd_core",
        "yaqd_fakes",
    }
)

_DYNAMIC_IMPORT_NAMES = {"__import__", "import_module"}


def check_candidate_imports(candidate_path: Path) -> list[str]:
    """Return forbidden static and literal dynamic imports."""
    tree = ast.parse(candidate_path.read_text(encoding="utf-8"), filename=str(candidate_path))
    violations: set[str] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Call) and _is_dynamic_import_call(node.func):
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                names.append(node.args[0].value)
        for name in names:
            if name.split(".", 1)[0] in FORBIDDEN_IMPORT_ROOTS:
                violations.add(name)
    return sorted(violations)


def _is_dynamic_import_call(function: ast.expr) -> bool:
    if isinstance(function, ast.Name):
        return function.id in _DYNAMIC_IMPORT_NAMES
    return isinstance(function, ast.Attribute) and function.attr == "import_module"
