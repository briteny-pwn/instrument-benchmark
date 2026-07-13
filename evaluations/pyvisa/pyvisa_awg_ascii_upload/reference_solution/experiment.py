"""Reference solution using only the raw socket simulator protocol."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path


RESOURCE = "USB0::0x9999::0x0100::AWG100001::INSTR"
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
    try:
        handle = client.open(RESOURCE)
        identity = client.query(handle, "*IDN?")
        client.write(handle, "*RST")
        client.write(handle, "DATA:ARB RAMP," + ",".join(f"{point:.6f}" for point in POINTS))
        client.write(handle, "FUNC:ARB RAMP")
        client.write(handle, "VOLT 2")
        client.write(handle, "OUTP ON")
        output_response = client.query(handle, "OUTP?").strip().upper()
        output_enabled = output_response in {"1", "ON"}
        result = {
            "instrument": identity.split(",")[1],
            "waveform": "RAMP",
            "points": POINTS,
            "point_count": len(POINTS),
            "amplitude_vpp": 2.0,
            "output_enabled": output_enabled,
        }
        if output_path:
            Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        client.close()
