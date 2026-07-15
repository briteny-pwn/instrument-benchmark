"""Compatibility facade for candidate import restrictions."""

from __future__ import annotations

from benchmark_harness.forbidden_imports import FORBIDDEN_IMPORT_ROOTS, check_candidate_imports


__all__ = ["FORBIDDEN_IMPORT_ROOTS", "check_candidate_imports"]
