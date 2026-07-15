from simulator.fake_device import build_device


def test_default_trigger_value_remains_one():
    device, signal = build_device(trigger_value=1, accepted_token=1)
    device.trigger()
    assert signal.state == "complete"
