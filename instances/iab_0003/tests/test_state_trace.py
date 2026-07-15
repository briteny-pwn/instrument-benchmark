from simulator.fake_device import build_device


def test_trigger_state_trace():
    device, signal = build_device(trigger_value=5, accepted_token=5)
    device.trigger(); signal.save()
    assert signal.state == "complete"
