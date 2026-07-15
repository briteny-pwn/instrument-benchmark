from simulator.fake_tcpip import FakeSocketModule, load_instrument


def test_default_tcpip_open_supports_legacy_driver():
    sockets = FakeSocketModule(); Instrument = load_instrument(sockets)
    class LegacySerialInstrument(Instrument):
        def __init__(self, communicator): self.communicator = communicator
    instrument = LegacySerialInstrument.open_tcpip("bridge", 9001)
    assert instrument.communicator.socket is sockets.created[0]
