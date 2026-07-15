import json
import os
from pathlib import Path
from types import SimpleNamespace

try:
    from evaluator.source_loader import load_class_methods
except ModuleNotFoundError:
    from simulator.source_loader import load_class_methods


class FakeTime:
    def __init__(self): self.now = 0.0
    def time(self): return self.now
    def sleep(self, duration): self.now += duration


class FakeChildSignal:
    def __init__(self, connected=True, name="sig"):
        self._connected, self.accesses = connected, 0
        self.dotted_name, self.pvname = name, f"SIM:{name}"
    @property
    def connected(self): self.accesses += 1; return self._connected


def load_device():
    source = Path(os.environ["IAB_REPOSITORY"]) / "ophyd/device.py"
    sentinel, clock = object(), FakeTime()
    Device = load_class_methods(
        source, "Device", {"set_defaults", "connection_timeout", "wait_for_connection"},
        globals_dict={"DEFAULT_CONNECTION_TIMEOUT": sentinel, "ttime": clock},
        class_attributes={"__any_instantiated": False, "__default_connection_timeout": 10.0},
    )
    return Device, sentinel, clock


def build_device(Device, signals, timeout):
    device = object.__new__(Device)
    device._connection_timeout = timeout
    device._required_for_connection = {}
    device.name = "sim_device"
    device.walk_signals = lambda include_lazy=False: [SimpleNamespace(item=signal) for signal in signals]
    device.walk_subdevices = lambda include_lazy=False: []
    return device


def save_timeout_trace(timeout):
    trace = [{"action": "wait_connection", "timeout": timeout, "state_before": "disconnected", "result": "timeout", "state_after": "disconnected"}]
    Path(os.environ["IAB_TRACE_PATH"]).write_text(json.dumps(trace))
