"""Load selected methods from an exact upstream file without importing its dependencies."""

from __future__ import annotations

import ast
import copy
from pathlib import Path
from typing import Any


def load_class_methods(
    path: Path,
    class_name: str,
    method_names: set[str],
    *,
    globals_dict: dict[str, Any] | None = None,
    class_attributes: dict[str, bool | float | int | str | None] | None = None,
) -> type:
    """Compile real method AST nodes inside a dependency-free class shell."""
    tree = ast.parse(path.read_text(), filename=str(path))
    source_class = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name), None)
    if source_class is None: raise LookupError(f"class {class_name} not found in {path}")
    methods = [copy.deepcopy(node) for node in source_class.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in method_names]
    for method in methods:
        method.decorator_list = [decorator for decorator in method.decorator_list if isinstance(decorator, ast.Name) and decorator.id in {"classmethod", "staticmethod", "property"}]
    found = {node.name for node in methods}
    if found != method_names: raise LookupError(f"missing methods in pre-fix source: {sorted(method_names - found)}")
    assignments = [ast.Assign(targets=[ast.Name(id=name, ctx=ast.Store())], value=ast.Constant(value=value)) for name, value in (class_attributes or {}).items()]
    shell = ast.ClassDef(name=class_name, bases=[], keywords=[], body=assignments + methods, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[shell], type_ignores=[]))
    namespace = dict(globals_dict or {})
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[class_name]
