from simulator.fake_tcpip import FakeSocketModule, load_instrument


def test_connection_trace():
    sockets = FakeSocketModule(); Instrument = load_instrument(sockets)
    class LegacySerialInstrument(Instrument):
        def __init__(self, communicator):
            self.communicator = communicator
            communicator.socket.trace.append({"action": "construct", "driver": "legacy"})
    LegacySerialInstrument.open_tcpip("bridge", 9001); sockets.save()
    assert sockets.created[0].closed is False
