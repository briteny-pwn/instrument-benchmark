from simulator.fake_connection import FakeChildSignal, build_device, load_device, save_timeout_trace


def test_disconnected_child_trace_and_error():
    Device, _, _ = load_device(); Device.set_defaults(connection_timeout=0.2)
    child = FakeChildSignal(connected=False)
    device = build_device(Device, [child], Device._Device__default_connection_timeout)
    try: device.wait_for_connection()
    except TimeoutError: pass
    else: raise AssertionError("timeout was swallowed")
    save_timeout_trace(device.connection_timeout)
    assert child.accesses > 1
