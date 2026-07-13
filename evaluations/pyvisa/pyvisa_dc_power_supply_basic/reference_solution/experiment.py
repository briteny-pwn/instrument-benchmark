"""Reference solution using only the raw socket simulator protocol."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path


RESOURCE = "USB0::0x9999::0x0001::DP100001::INSTR"


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
    try:
        handle = client.open(RESOURCE)
        identity = client.query(handle, "*IDN?")
        client.write(handle, ":SOURce1:VOLTage 3.3")
        client.write(handle, ":SOURce1:CURRent 0.5")
        client.write(handle, ":OUTPut CH1,ON")
        measured_voltage = float(client.query(handle, ":MEASure:VOLTage? CH1"))
        result = {
            "instrument": identity.split(",")[1],
            "channel": 1,
            "target_voltage_v": 3.3,
            "current_limit_a": 0.5,
            "measured_voltage_v": measured_voltage,
            "output_enabled": True,
        }
        if output_path:
            Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        client.close()

