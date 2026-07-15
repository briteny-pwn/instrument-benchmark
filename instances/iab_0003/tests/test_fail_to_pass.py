from simulator.fake_device import build_device


def test_component_trigger_value_is_used():
    device, signal = build_device(trigger_value=5, accepted_token=5)
    status = device.trigger()
    assert status.device is device
    assert signal.trace[0]["value"] == 5
