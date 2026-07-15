"""Materialize the model-visible side of an executable instance."""

from __future__ import annotations

import shutil
from pathlib import Path


def build_model_bundle(instance: Path, output: Path) -> Path:
    if output.exists(): shutil.rmtree(output)
    output.mkdir(parents=True)
    shutil.copy2(instance / "problem.md", output / "problem.md")
    shutil.copytree(instance / "repository", output / "repository", ignore=shutil.ignore_patterns("source_manifest.json", "__pycache__", "*.pyc"))
    shutil.copytree(instance / "simulator", output / "simulator", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(Path(__file__).with_name("source_loader.py"), output / "simulator" / "source_loader.py")
    return output
