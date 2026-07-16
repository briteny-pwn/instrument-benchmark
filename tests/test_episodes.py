from pathlib import Path
from tempfile import TemporaryDirectory

from evaluator.episode import run_episode


def test_realistic_integration_episodes_pass_contract():
    root = Path(__file__).parents[1]
    reports = [run_episode(root / "episodes" / f"iep_{index:04d}") for index in range(1, 4)]
    assert all(report["strict_pass"] for report in reports)
    assert all(report["score"] == 100.0 for report in reports)
    assert all(len(report["scenarios"]) == 3 for report in reports)


def test_episode_patch_application_isolated():
    root = Path(__file__).parents[1]
    with TemporaryDirectory() as directory:
        patch = Path(directory) / "invalid.patch"
        patch.write_text("not a unified diff\n")
        report = run_episode(root / "episodes" / "iep_0001", patch)
    assert report["failure_kind"] == "patch_apply"
    assert report["score"] == 0.0
