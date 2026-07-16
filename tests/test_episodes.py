from pathlib import Path
from tempfile import TemporaryDirectory

from evaluator.episode import run_episode


def test_realistic_integration_episodes_pass_contract():
    root = Path(__file__).parents[1]
    for index in range(1, 4):
        episode = root / "episodes" / f"iep_{index:04d}"
        pre = run_episode(episode)
        gold = run_episode(episode, repository=episode / "gold")
        assert not pre["strict_pass"]
        assert gold["strict_pass"] and gold["score"] == 100.0
        assert len(gold["scenarios"]) == 3


def test_episode_patch_application_isolated():
    root = Path(__file__).parents[1]
    with TemporaryDirectory() as directory:
        patch = Path(directory) / "invalid.patch"
        patch.write_text("not a unified diff\n")
        report = run_episode(root / "episodes" / "iep_0001", patch)
    assert report["failure_kind"] == "patch_apply"
    assert report["score"] == 0.0


def test_episode_accepts_non_patch_implementation_directory():
    root = Path(__file__).parents[1]
    episode = root / "episodes" / "iep_0001"
    report = run_episode(episode, submission=episode / "gold")
    assert report["submission_mode"] == "directory"
    assert report["strict_pass"] is True
    assert report["score"] == 100.0
