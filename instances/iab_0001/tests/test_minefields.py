from simulator.fake_connection import FakeChildSignal, build_device, load_device


def test_instance_override_wins_over_class_default():
    Device, _, _ = load_device(); Device.set_defaults(connection_timeout=0.2)
    device = build_device(Device, [FakeChildSignal()], timeout=0.05)
    assert device.connection_timeout == 0.05
    device.wait_for_connection()


def test_defaults_cannot_change_after_instantiation_boundary():
    Device, _, _ = load_device(); Device._Device__any_instantiated = True
    try: Device.set_defaults(connection_timeout=0.1)
    except RuntimeError: return
    raise AssertionError("class defaults changed after the lifecycle boundary")


def test_all_children_are_checked():
    Device, _, _ = load_device(); first, second = FakeChildSignal(), FakeChildSignal()
    build_device(Device, [first, second], timeout=0.1).wait_for_connection()
    assert first.accesses == second.accesses == 1
