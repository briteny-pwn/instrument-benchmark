"""Compile and load a focused C++ semantic projection for adapter instances."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
from pathlib import Path
from typing import Any


def source_text(repository: Path, paths: list[str]) -> str:
    return "\n".join((repository / path).read_text(errors="ignore") for path in paths if (repository / path).is_file())


def analyze(repository: Path, spec: dict[str, Any]) -> dict[str, bool]:
    text = source_text(repository, spec["source_paths"])
    values = {}
    for name, rule in spec["rules"].items():
        all_terms = rule.get("all", [])
        any_terms = rule.get("any", [])
        values[name] = all(term in text for term in all_terms) and (not any_terms or any(term in text for term in any_terms))
    return values


def _library_path(build: Path) -> Path:
    suffixes = (".so", ".dylib", ".dll")
    matches = [path for path in build.rglob("*") if path.is_file() and path.name.lower().endswith(suffixes) and "iab_contract" in path.name]
    if not matches: raise FileNotFoundError("compiled iab_contract library was not produced")
    return matches[0]


def build_and_load(instance: Path, repository: Path, work: Path, spec: dict[str, Any]) -> tuple[ctypes.CDLL, dict[str, bool]]:
    values = analyze(repository, spec)
    generated = work / "cpp_generated"
    generated.mkdir(parents=True, exist_ok=True)
    entries = "\n".join(f'{{"{name}", {1 if value else 0}}},' for name, value in sorted(values.items()))
    (generated / "contract_entries.inc").write_text(entries + "\n")
    build = work / "cpp_build"
    configure = subprocess.run(
        ["cmake", "-S", str(instance / "simulator"), "-B", str(build), f"-DIAB_GENERATED_DIR={generated}"],
        text=True, capture_output=True,
    )
    if configure.returncode: raise RuntimeError("cmake configure failed\n" + configure.stdout[-2000:] + configure.stderr[-2000:])
    compile_result = subprocess.run(["cmake", "--build", str(build), "--config", "Release"], text=True, capture_output=True)
    if compile_result.returncode: raise RuntimeError("cmake build failed\n" + compile_result.stdout[-2000:] + compile_result.stderr[-2000:])
    library = ctypes.CDLL(str(_library_path(build)))
    library.iab_contract_value.argtypes = [ctypes.c_char_p]
    library.iab_contract_value.restype = ctypes.c_int
    return library, values


class Contract:
    def __init__(self, instance: Path, spec: dict[str, Any]):
        repository = Path(os.environ["IAB_REPOSITORY"])
        work = repository.parent
        self.library, self.values = build_and_load(instance, repository, work, spec)

    def value(self, name: str) -> bool:
        return self.library.iab_contract_value(name.encode()) == 1


def load_spec(instance: Path) -> dict[str, Any]:
    return json.loads((instance / "tests" / "contract_spec.json").read_text())


def save_trace(events: list[dict[str, Any]]) -> None:
    Path(os.environ["IAB_TRACE_PATH"]).write_text(json.dumps(events))
