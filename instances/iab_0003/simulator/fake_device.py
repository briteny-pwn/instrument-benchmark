import json
import os
from pathlib import Path
from types import SimpleNamespace

try:
    from evaluator.source_loader import load_class_methods
except ModuleNotFoundError:
    from simulator.source_loader import load_class_methods


class FakeDeviceStatus:
    def __init__(self, device): self.device, self.finished = device, False
    def set_finished(self): self.finished = True
    def _finished(self, **kwargs): self.finished = True


class FakeTriggerSignal:
    attr_name = "trigger"

    def __init__(self, accepted_token):
        self.accepted_token, self.state, self.trace = accepted_token, "idle", []

    def put(self, value, *, wait, callback):
        before = self.state
        if before != "idle": raise RuntimeError("trigger while device is busy")
        self.trace.append({"action": "trigger", "value": value, "state_before": before})
        if value != self.accepted_token: raise ValueError("instrument rejected trigger token")
        self.state = "acquiring"; self.trace[-1]["state_after"] = self.state
        callback(); return None

    def complete(self):
        self.state = "complete"
        self.trace.append({"action": "complete", "state_before": "acquiring", "state_after": "complete"})

    def save(self): Path(os.environ["IAB_TRACE_PATH"]).write_text(json.dumps(self.trace))


def build_device(trigger_value, accepted_token):
    source = Path(os.environ["IAB_REPOSITORY"]) / "ophyd/device.py"
    Device = load_class_methods(source, "Device", {"trigger"}, globals_dict={"DeviceStatus": FakeDeviceStatus})
    signal, device = FakeTriggerSignal(accepted_token), object.__new__(Device)
    device.trigger_signals = [signal]
    device.SUB_ACQ_DONE = "acq_done"
    device._sig_attrs = {signal.attr_name: SimpleNamespace(trigger_value=trigger_value)}
    device.subscribe = lambda *args, **kwargs: None
    device._done_acquiring = signal.complete
    return device, signal
