"""Reference solution using only the raw socket simulator protocol."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path


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

    def open(self, resource: str) -> str:
        handle = self.request({"op": "open", "resource": resource, "timeout": 10000})["handle"]
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
    trace_cleared = False
    try:
        resource = None
        identity = None
        for candidate in client.request({"op": "list_resources"})["resources"]:
            candidate_handle = client.open(candidate)
            candidate_identity = client.query(candidate_handle, "*IDN?")
            if candidate_identity.split(",")[1] == "MockDMM2000":
                resource = candidate
                handle = candidate_handle
                identity = candidate_identity
                break
            client.request({"op": "close", "handle": candidate_handle})
            client.handles.remove(candidate_handle)
        if resource is None or handle is None or identity is None:
            raise RuntimeError("MockDMM2000 resource not found")
        client.write(handle, "*RST")
        client.write(handle, "CONF:VOLT:DC")
        client.write(handle, "VOLT:RANG 10")
        client.write(handle, "VOLT:RES 0.001")
        client.write(handle, "SAMP:COUN 5")
        client.write(handle, "INIT")
        samples = [float(item) for item in client.query(handle, "TRACE:DATA?").split(",")]
        client.write(handle, "TRACE:CLEAR")
        trace_cleared = True
        result = {
            "instrument": identity.split(",")[1],
            "resource": resource,
            "measurement": "dc_voltage",
            "sample_count": len(samples),
            "samples_v": samples,
            "average_voltage_v": sum(samples) / len(samples),
            "unit": "V",
        }
        if output_path:
            Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        if handle is not None and not trace_cleared:
            client.write(handle, "TRACE:CLEAR")
        client.close()
