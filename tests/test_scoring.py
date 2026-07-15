from iab.scoring import hard_filter_reasons, score_candidate


def test_score_boundaries():
    all_true = {key: True for key in __import__("iab.scoring", fromlist=["WEIGHTS"]).WEIGHTS}
    assert score_candidate({"evidence": all_true})["score"] == 100
    assert score_candidate({"evidence": all_true})["grade"] == "verified_candidate"


def test_hard_filter_requires_provenance():
    candidate = {"evidence": {"has_merged_pr": True, "touches_driver_adapter": True, "real_instrument": True, "no_real_hardware": True}}
    assert hard_filter_reasons(candidate) == ["missing pre/post fix commit"]


def test_hard_filter_rejects_non_executable_sources():
    base = {
        "pre_fix_commit": "a" * 40,
        "post_fix_commit": "b" * 40,
        "change_kind": "docs",
        "requires_real_hardware": True,
        "uses_private_sdk": True,
        "evidence": {"has_merged_pr": True, "touches_driver_adapter": True, "real_instrument": True, "no_real_hardware": True},
    }
    reasons = hard_filter_reasons(base)
    assert "excluded change kind: docs" in reasons
    assert "requires real hardware" in reasons
    assert "uses private SDK or manual" in reasons
