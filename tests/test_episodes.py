from pathlib import Path

from evaluator.episode import run_episode


def test_realistic_integration_episodes_pass_contract():
    root = Path(__file__).parents[1]
    reports = [run_episode(root / "episodes" / f"iep_{index:04d}") for index in range(1, 4)]
    assert all(report["strict_pass"] for report in reports)
    assert all(report["score"] == 100.0 for report in reports)
    assert all(len(report["scenarios"]) == 3 for report in reports)
