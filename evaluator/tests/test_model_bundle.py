from pathlib import Path
from tempfile import TemporaryDirectory

from evaluator.model_bundle import build_model_bundle


def test_bundle_excludes_hidden_evaluation_material():
    with TemporaryDirectory() as tmp:
        root = Path(tmp); instance = root / "instance"; output = root / "bundle"
        (instance / "repository").mkdir(parents=True); (instance / "simulator").mkdir()
        (instance / "problem.md").write_text("task")
        (instance / "repository/code.py").write_text("bug = True")
        (instance / "repository/source_manifest.json").write_text("secret commit")
        (instance / "simulator/fake.py").write_text("state = 'idle'")
        (instance / "patches").mkdir(); (instance / "patches/gold.patch").write_text("gold")
        build_model_bundle(instance, output)
        assert {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()} == {"problem.md", "repository/code.py", "simulator/fake.py", "simulator/source_loader.py"}
