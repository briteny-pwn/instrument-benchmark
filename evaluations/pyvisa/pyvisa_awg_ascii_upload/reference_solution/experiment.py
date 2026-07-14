"""Reference solution using only the raw socket simulator protocol."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path


POINTS = [0.0, 0.25, 0.5, 0.75, 1.0]


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
        handle = self.request({"op": "open", "resource": resource, "timeout": 6000})["handle"]
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
            if candidate_identity.split(",")[1] == "MockAWG100":
                resource = candidate
                handle = candidate_handle
                identity = candidate_identity
                break
            client.request({"op": "close", "handle": candidate_handle})
            client.handles.remove(candidate_handle)
        if resource is None or handle is None or identity is None:
            raise RuntimeError("MockAWG100 resource not found")
        client.write(handle, "*RST")
        client.write(handle, "DATA:ARB RAMP," + ",".join(f"{point:.6f}" for point in POINTS))
        client.write(handle, "FUNC:ARB RAMP")
        client.write(handle, "VOLT 2")
        client.write(handle, "FREQ 1000")
        client.write(handle, "OUTP ON")
        output_enabled = True
        output_response = client.query(handle, "OUTP?").strip().upper()
        output_enabled_during_verification = output_response in {"1", "ON"}
        client.write(handle, "OUTP OFF")
        output_enabled = False
        result = {
            "instrument": identity.split(",")[1],
            "resource": resource,
            "waveform": "RAMP",
            "points": POINTS,
            "point_count": len(POINTS),
            "amplitude_vpp": 2.0,
            "frequency_hz": 1000.0,
            "output_enabled_during_verification": output_enabled_during_verification,
            "final_output_enabled": False,
        }
        if output_path:
            Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        if handle is not None and output_enabled:
            client.write(handle, "OUTP OFF")
        client.close()
