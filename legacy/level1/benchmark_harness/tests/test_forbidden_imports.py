from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from benchmark_harness.forbidden_imports import check_candidate_imports
from evaluations.common import grader_core, import_guard


class ForbiddenImportTests(unittest.TestCase):
    def check_source(self, source: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmpdir:
            candidate = Path(tmpdir) / "solution.py"
            candidate.write_text(source, encoding="utf-8")
            return check_candidate_imports(candidate)

    def test_static_and_literal_dynamic_imports_share_one_policy(self) -> None:
        self.assertIs(import_guard.FORBIDDEN_IMPORT_ROOTS, grader_core.import_guard.FORBIDDEN_IMPORT_ROOTS)
        cases = {
            "import pyvisa": ["pyvisa"],
            "from qcodes.instrument import Instrument": ["qcodes.instrument"],
            "__import__('epics.ca')": ["epics.ca"],
            "importlib.import_module('tango.server')": ["tango.server"],
            "from importlib import import_module\nimport_module('yaqc')": ["yaqc"],
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(self.check_source(source), expected)

    def test_runtime_guard_covers_importlib_import_module(self) -> None:
        import importlib

        with self.assertRaisesRegex(RuntimeError, "Forbidden instrument/framework import"):
            with grader_core._blocked_imports():
                importlib.import_module("pyvisa")

    def test_allowed_dynamic_import_is_not_reported(self) -> None:
        self.assertEqual(self.check_source("importlib.import_module('json')"), [])


if __name__ == "__main__":
    unittest.main()
