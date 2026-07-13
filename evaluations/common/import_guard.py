"""Import restrictions for from-scratch instrument-interface candidates."""

from __future__ import annotations

import ast
from pathlib import Path


FORBIDDEN_IMPORT_ROOTS = {
    "caproto",
    "epics",
    "pyvisa",
    "pyepics",
    "qcodes",
    "qcodes_contrib_drivers",
    "lab_drivers",
    "pymeasure",
    "pcaspy",
    "softioc",
    "bluesky",
    "ophyd",
    "pylabrobot",
    "opentrons",
    "evaluations",
}


def check_candidate_imports(candidate_path: Path) -> list[str]:
    tree = ast.parse(candidate_path.read_text(encoding="utf-8"), filename=str(candidate_path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in FORBIDDEN_IMPORT_ROOTS:
                    violations.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            root = node.module.split(".", 1)[0]
            if root in FORBIDDEN_IMPORT_ROOTS:
                violations.append(node.module)
    return sorted(set(violations))
