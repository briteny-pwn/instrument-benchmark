import ast
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluator.source_loader import load_class_methods


def test_loads_real_method_without_module_imports():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "source.py"
        path.write_text("import unavailable_dependency\nclass Driver:\n    def read(self):\n        return self.value\n")
        Driver = load_class_methods(path, "Driver", {"read"})
        driver = object.__new__(Driver); driver.value = 7
        assert driver.read() == 7


def test_missing_prefixed_method_is_observable():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "source.py"; path.write_text("class Driver:\n    pass\n")
        try: load_class_methods(path, "Driver", {"repair"})
        except LookupError: return
        raise AssertionError("missing method was accepted")
