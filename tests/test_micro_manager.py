import json
import sys
from types import SimpleNamespace
from pathlib import Path

# The miner needs PyYAML only when loading configuration. Keep this unit test
# runnable in the standard-library evaluator environment.
sys.modules.setdefault("yaml", SimpleNamespace(safe_load=lambda _: {}))
from scripts.mine_github_issues import adapter_name, path_allowed


def test_device_adapter_path_filtering():
    source = {"path_prefixes": ["DeviceAdapters/"]}
    assert path_allowed(source, "DeviceAdapters/DemoCamera/DemoCamera.cpp")
    assert path_allowed({"path_prefixes": ["MMCore/"]}, "MMCore/MMCore.cpp")
    assert not path_allowed(source, "README.md")


def test_micro_manager_snapshot_and_verified_counts():
    root = Path(__file__).parents[1]
    candidates = json.loads((root / "data/micro_manager_scored_candidates.json").read_text())
    assert len(candidates) == 20
    assert all(c["source_type"] == "merged_pr_with_reproduction" for c in candidates)
    assert all(adapter_name(c["changed_paths"]) for c in candidates)
    assert len(list((root / "data/micro_manager_verified_candidates").glob("iab_*"))) == 10
