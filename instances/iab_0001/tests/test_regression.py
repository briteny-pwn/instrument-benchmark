from simulator.fake_connection import FakeChildSignal, build_device, load_device


def test_instance_timeout_override_is_preserved():
    Device, _, _ = load_device(); Device.set_defaults(connection_timeout=0.2)
    child = FakeChildSignal()
    device = build_device(Device, [child], timeout=0.75)
    assert device.connection_timeout == 0.75
    assert device.wait_for_connection() is None
