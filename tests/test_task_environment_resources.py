import os

import pytest


def test_long_report_path_keeps_private_short_transport(tmp_path):
    from instrument_benchmark.task_environment_resources import TaskEnvironmentResources

    root = tmp_path / ("report-" + "x" * 120) / "attempt"
    resources = TaskEnvironmentResources.allocate(root)
    try:
        assert len(str(resources.transport_root / "task.sock").encode()) <= 100
        assert resources.candidate_root == root / "candidate"
        assert not resources.transport_root.is_relative_to(root)
        for path in (
            resources.candidate_root,
            resources.evidence_root,
            resources.transport_root,
        ):
            assert path.stat().st_mode & 0o777 == 0o700
        (resources.transport_root / "task.ready").write_text("probe")
    finally:
        resources.close_transport()
    assert resources.candidate_root.exists()
    assert resources.evidence_root.exists()
    assert not resources.transport_root.exists()
    resources.close_transport()


def test_root_identity_is_rejected_without_allocating(tmp_path, monkeypatch):
    from instrument_benchmark.task_environment_resources import TaskEnvironmentResources

    monkeypatch.setattr(os, "getuid", lambda: 0)
    with pytest.raises(ValueError, match="non-root"):
        TaskEnvironmentResources.allocate(tmp_path / "run")
    assert not (tmp_path / "run").exists()


def test_cleanup_does_not_follow_replaced_transport(tmp_path):
    from instrument_benchmark.task_environment_resources import TaskEnvironmentResources

    resources = TaskEnvironmentResources.allocate(tmp_path / "run")
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep").touch()
    resources.transport_root.rmdir()
    resources.transport_root.symlink_to(other)
    try:
        with pytest.raises(ValueError, match="replaced"):
            resources.close_transport()
        assert (other / "keep").exists()
    finally:
        resources.transport_root.unlink()
