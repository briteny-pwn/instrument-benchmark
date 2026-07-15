from simulator.fake_device import build_device


def test_no_hardcoded_token_or_duplicate_trigger():
    device, signal = build_device(trigger_value=7, accepted_token=7)
    device.trigger()
    assert [event["action"] for event in signal.trace].count("trigger") == 1


def test_signal_errors_are_not_swallowed():
    device, _ = build_device(trigger_value=8, accepted_token=9)
    try: device.trigger()
    except ValueError: return
    raise AssertionError("the driver swallowed a simulator rejection")
