from simulator.fake_tcpip import FakeSocketModule, load_instrument


def legacy_type(sockets):
    Instrument = load_instrument(sockets)
    class LegacySerialInstrument(Instrument):
        def __init__(self, communicator): self.communicator = communicator
    return LegacySerialInstrument


def test_explicit_auth_is_not_silently_discarded():
    sockets = FakeSocketModule()
    try: legacy_type(sockets).open_tcpip("bridge", 9001, auth=("u", "p"))
    except TypeError: return
    raise AssertionError("explicit credentials were silently discarded")


def test_one_socket_and_one_connection():
    sockets = FakeSocketModule(); legacy_type(sockets).open_tcpip("bridge", 9001)
    assert len(sockets.created) == 1
    assert [event["action"] for event in sockets.trace].count("connect") == 1
