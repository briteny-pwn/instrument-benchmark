from simulator.fake_tcpip import FakeSocketModule, load_instrument


def test_explicit_auth_is_forwarded():
    sockets = FakeSocketModule(); Instrument = load_instrument(sockets)
    class AuthInstrument(Instrument):
        def __init__(self, communicator, auth=None): self.communicator, self.auth = communicator, auth
    instrument = AuthInstrument.open_tcpip("secure", 9002, auth=("user", "secret"))
    assert instrument.auth == ("user", "secret")
