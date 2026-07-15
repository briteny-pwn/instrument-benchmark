from pathlib import Path
from tempfile import TemporaryDirectory

from evaluator.unified_patch import apply_unified_patch, parse_unified_diff


def test_apply_change_with_context_and_insert():
    with TemporaryDirectory() as tmp:
        root = Path(tmp); (root / "code.py").write_text("one\ntwo\nthree\n")
        patch = root / "change.patch"
        patch.write_text("--- a/code.py\n+++ b/code.py\n@@ -1,3 +1,4 @@\n one\n-two\n+TWO\n+extra\n three\n")
        apply_unified_patch(root, patch)
        assert (root / "code.py").read_text() == "one\nTWO\nextra\nthree\n"


def test_rejects_path_escape():
    with TemporaryDirectory() as tmp:
        root = Path(tmp); patch = root / "bad.patch"
        patch.write_text("--- a/../outside\n+++ b/../outside\n@@ -0,0 +1 @@\n+bad\n")
        try: apply_unified_patch(root, patch)
        except ValueError: return
        raise AssertionError("path traversal was accepted")


def test_requires_a_file_change():
    try: parse_unified_diff("not a patch")
    except ValueError: return
    raise AssertionError("invalid patch was accepted")
