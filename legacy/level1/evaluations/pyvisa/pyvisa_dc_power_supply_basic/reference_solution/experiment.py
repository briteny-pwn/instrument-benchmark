"""Reference solution using only the raw socket simulator protocol."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path


class RawInstrumentClient:
    def __init__(self) -> None:
        host = os.environ["INSTRUMENT_SIM_HOST"]
        port = int(os.environ["INSTRUMENT_SIM_PORT"])
        self.sock = socket.create_connection((host, port), timeout=5)
        self.file = self.sock.makefile("rwb")
        self.handles: list[str] = []

    def request(self, payload: dict) -> dict:
        self.file.write((json.dumps(payload) + "\n").encode("utf-8"))
        self.file.flush()
        response = json.loads(self.file.readline().decode("utf-8"))
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "raw simulator error"))
        return response

    def open(self, resource: str) -> str:
        handle = self.request({"op": "open", "resource": resource, "timeout": 5000})["handle"]
        self.handles.append(handle)
        return handle

    def write(self, handle: str, command: str) -> None:
        self.request({"op": "write", "handle": handle, "command": command})

    def query(self, handle: str, command: str) -> str:
        return self.request({"op": "query", "handle": handle, "command": command})["response"].strip()

    def close(self) -> None:
        for handle in list(self.handles):
            self.request({"op": "close", "handle": handle})
        self.file.close()
        self.sock.close()


def run_experiment(output_path: str = "result.json") -> dict:
    client = RawInstrumentClient()
    handle = None
    output_enabled = False
    try:
        resource = None
        identity = None
        for candidate in client.request({"op": "list_resources"})["resources"]:
            candidate_handle = client.open(candidate)
            candidate_identity = client.query(candidate_handle, "*IDN?")
            if candidate_identity.split(",")[1] == "MockDP100":
                resource = candidate
                handle = candidate_handle
                identity = candidate_identity
                break
            client.request({"op": "close", "handle": candidate_handle})
            client.handles.remove(candidate_handle)
        if resource is None or handle is None or identity is None:
            raise RuntimeError("MockDP100 resource not found")
        client.write(handle, ":SOURce1:VOLTage 3.3")
        client.write(handle, ":SOURce1:CURRent 0.5")
        client.write(handle, ":OUTPut CH1,ON")
        output_enabled = True
        measured_voltage = float(client.query(handle, ":MEASure:VOLTage? CH1"))
        client.write(handle, ":OUTPut CH1,OFF")
        output_enabled = False
        result = {
            "instrument": identity.split(",")[1],
            "resource": resource,
            "channel": 1,
            "target_voltage_v": 3.3,
            "current_limit_a": 0.5,
            "measured_voltage_v": measured_voltage,
            "output_enabled_during_measurement": True,
            "final_output_enabled": False,
        }
        if output_path:
            Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        if handle is not None and output_enabled:
            client.write(handle, ":OUTPut CH1,OFF")
        client.close()
