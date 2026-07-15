from evaluator.run_instance import scored_report
from evaluator.trace_compare import compare_trace_progress


def test_partial_score_is_continuous():
    layers = {
        "fail_to_pass": {"passed": False, "tests": [{"passed": True}, {"passed": False}]},
        "regression": {"passed": True, "tests": [{"passed": True}]},
        "state_trace": {"passed": True, "tests": [{"passed": True}]},
        "minefields": {"passed": False, "tests": [{"passed": False}]},
        "gold_differential": {"passed": False, "matched": 1, "total": 2, "errors": []},
    }
    report = scored_report("evaluate", layers, False)
    assert 0 < report["score"] < 100
    assert report["schema_version"] == 2
    assert report["strict_pass"] is False


def test_trace_checkpoint_ratio():
    matched, errors = compare_trace_progress([{"event": "a"}], [{"event": "a"}, {"event": "b"}])
    assert matched == 1
    assert errors
