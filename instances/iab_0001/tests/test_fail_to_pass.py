from simulator.fake_connection import FakeChildSignal, build_device, load_device


def test_class_wide_device_connection_timeout():
    Device, _, _ = load_device()
    Device.set_defaults(connection_timeout=0.2)
    assert Device._Device__default_connection_timeout == 0.2
    child = FakeChildSignal()
    build_device(Device, [child], Device._Device__default_connection_timeout).wait_for_connection()
    assert child.accesses >= 1
