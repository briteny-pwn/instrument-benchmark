import json
import os
from pathlib import Path

try:
    from evaluator.source_loader import load_class_methods
except ModuleNotFoundError:
    from simulator.source_loader import load_class_methods


class FakeSocket:
    def __init__(self, trace): self.trace, self.closed = trace, False
    def connect(self, address): self.trace.append({"action": "connect", "host": address[0], "port": address[1]})
    def close(self): self.closed = True; self.trace.append({"action": "close"})


class FakeSocketModule:
    def __init__(self): self.trace, self.created = [], []
    def socket(self):
        value = FakeSocket(self.trace); self.created.append(value); return value
    def save(self): Path(os.environ["IAB_TRACE_PATH"]).write_text(json.dumps(self.trace))


class FakeSocketCommunicator:
    def __init__(self, socket): self.socket = socket


def load_instrument(socket_module):
    source = Path(os.environ["IAB_REPOSITORY"]) / "src/instruments/abstract_instruments/instrument.py"
    return load_class_methods(source, "Instrument", {"open_tcpip"}, globals_dict={"socket": socket_module, "SocketCommunicator": FakeSocketCommunicator})
