from evaluator.trace_compare import compare_traces


def test_comparison_allows_extra_events_and_timestamps():
    actual = [{"action": "connect", "time": 1}, {"action": "debug"}, {"action": "trigger", "value": 3}]
    assert compare_traces(actual, [{"action": "connect"}, {"action": "trigger", "value": 3}]) == (True, [])


def test_comparison_enforces_order():
    passed, errors = compare_traces([{"action": "b"}, {"action": "a"}], [{"action": "a"}, {"action": "b"}])
    assert not passed and errors
