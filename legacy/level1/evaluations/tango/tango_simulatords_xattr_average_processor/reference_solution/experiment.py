"""Reference solution using only the raw socket simulator protocol."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path


RESOURCES = {
    "sensor_a": "TANGO://sim/sensor/a",
    "sensor_b": "TANGO://sim/sensor/b",
    "processor": "TANGO://sim/processor/avg",
}


class Client:
    def __init__(self) -> None:
        self.sock = socket.create_connection((os.environ["INSTRUMENT_SIM_HOST"], int(os.environ["INSTRUMENT_SIM_PORT"])), timeout=5)
        self.file = self.sock.makefile("rwb")
        self.handles: list[str] = []

    def request(self, payload: dict) -> dict:
        self.file.write((json.dumps(payload) + "\n").encode("utf-8"))
        self.file.flush()
        response = json.loads(self.file.readline().decode("utf-8"))
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "simulator error"))
        return response

    def list_resources(self) -> list[str]:
        return self.request({"op": "list_resources"})["resources"]

    def open(self, resource: str) -> str:
        handle = self.request({"op": "open", "resource": resource, "timeout": 5000, "read_termination": "\n", "write_termination": "\n"})["handle"]
        self.handles.append(handle)
        return handle

    def query(self, handle: str, command: str) -> str:
        return self.request({"op": "query", "handle": handle, "command": command})["response"].strip()

    def close(self) -> None:
        for handle in list(self.handles):
            self.request({"op": "close", "handle": handle})
        self.file.close()
        self.sock.close()


def _value(reply: str) -> float:
    return float(reply.split()[1])


def run_experiment(output_path: str = "result.json") -> dict:
    client = Client()
    try:
        available = set(client.list_resources())
        handles = {name: client.open(resource) for name, resource in RESOURCES.items() if resource in available}
        sensor_values = [
            _value(client.query(handles["sensor_a"], "READ_ATTR temperature")),
            _value(client.query(handles["sensor_b"], "READ_ATTR temperature")),
        ]
        average = _value(client.query(handles["processor"], "READ_ATTR average_temperature"))
        deviation = _value(client.query(handles["processor"], "READ_ATTR deviation"))
        state = client.query(handles["processor"], "COMMAND State")
        expected_average = sum(sensor_values) / len(sensor_values)
        expected_deviation = abs(sensor_values[1] - sensor_values[0]) / 2
        result = {
            "devices": {name: resource.removeprefix("TANGO://") for name, resource in RESOURCES.items()},
            "sensor_temperatures_c": sensor_values,
            "average_temperature_c": average,
            "deviation_c": deviation,
            "processor_state": state,
            "validation_passed": abs(average - expected_average) < 1e-12 and abs(deviation - expected_deviation) < 1e-12,
        }
        Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        client.close()
