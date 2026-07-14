"""Reference solution using only the raw socket simulator protocol."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path


TARGET_MODEL = "MockLogger300"


class RawInstrumentClient:
    def __init__(self) -> None:
        self.sock = socket.create_connection((os.environ["INSTRUMENT_SIM_HOST"], int(os.environ["INSTRUMENT_SIM_PORT"])), timeout=5)
        self.file = self.sock.makefile("rwb")
        self.handles: list[str] = []

    def request(self, payload: dict) -> dict:
        self.file.write((json.dumps(payload) + "\n").encode("utf-8"))
        self.file.flush()
        response = json.loads(self.file.readline().decode("utf-8"))
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "raw simulator error"))
        return response

    def list_resources(self) -> list[str]:
        return self.request({"op": "list_resources"})["resources"]

    def open(self, resource: str) -> str:
        handle = self.request(
            {
                "op": "open",
                "resource": resource,
                "timeout": 4000,
                "read_termination": "\n",
                "write_termination": "\n",
            }
        )["handle"]
        self.handles.append(handle)
        return handle

    def query(self, handle: str, command: str) -> str:
        return self.request({"op": "query", "handle": handle, "command": command})["response"].strip()

    def write(self, handle: str, command: str) -> None:
        self.request({"op": "write", "handle": handle, "command": command})

    def close_handle(self, handle: str) -> None:
        self.request({"op": "close", "handle": handle})
        self.handles.remove(handle)

    def close(self) -> None:
        for handle in list(self.handles):
            self.close_handle(handle)
        self.file.close()
        self.sock.close()


def run_experiment(output_path: str = "result.json") -> dict:
    client = RawInstrumentClient()
    try:
        selected_handle = None
        selected_resource = ""
        selected_identity = ""
        for resource in client.list_resources():
            handle = client.open(resource)
            identity = client.query(handle, "*IDN?")
            if TARGET_MODEL in identity:
                selected_handle = handle
                selected_resource = resource
                selected_identity = identity
                break
            client.close_handle(handle)
        if selected_handle is None:
            raise RuntimeError("target logger not found")
        client.write(selected_handle, "SENS:CHAN A")
        result = {
            "instrument": selected_identity.split(",")[1],
            "selected_resource": selected_resource,
            "channel": "A",
            "temperature_c": float(client.query(selected_handle, "MEAS:TEMP? A")),
            "relative_humidity_percent": float(client.query(selected_handle, "MEAS:HUM? A")),
        }
        if output_path:
            Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        client.close()
