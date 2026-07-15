"""Reference solution using only the raw socket simulator protocol."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path


RESOURCE = "CA::PVBRIDGE::SIM"
SETPOINTS = [-0.2, 0.0, 0.2, 0.4]


class Client:
    def __init__(self) -> None:
        self.sock = socket.create_connection((os.environ["INSTRUMENT_SIM_HOST"], int(os.environ["INSTRUMENT_SIM_PORT"])), timeout=5)
        self.file = self.sock.makefile("rwb")
        self.handles: list[str] = []

    def request(self, payload: dict) -> dict:
        self.file.write((json.dumps(payload) + "\n").encode())
        self.file.flush()
        response = json.loads(self.file.readline().decode())
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "simulator error"))
        return response

    def list_resources(self) -> list[str]:
        return self.request({"op": "list_resources"})["resources"]

    def open(self, resource: str) -> str:
        handle = self.request({"op": "open", "resource": resource, "timeout": 5000, "read_termination": "\n", "write_termination": "\n"})["handle"]
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


def _last_float(reply: str) -> float:
    return float(reply.split()[-1])


def _last_int(reply: str) -> int:
    return int(reply.split()[-1])


def run_experiment(output_path: str = "result.json") -> dict:
    client = Client()
    try:
        resources = client.list_resources()
        handle = client.open(RESOURCE if RESOURCE in resources else resources[0])
        identity = client.query(handle, "*IDN?")
        readbacks: list[float] = []
        counts: list[int] = []
        history: list[str] = []
        for value in SETPOINTS:
            client.write(handle, f"PVPUT MOCK:BIAS:SP {value:.1f}")
            readbacks.append(_last_float(client.query(handle, "PVGET MOCK:BIAS:RBV")))
            counts.append(_last_int(client.query(handle, "PVGET MOCK:DETECTOR:COUNT")))
            history.append(client.query(handle, "MONITOR? MOCK:BIAS:SP"))
        slope = (counts[-1] - counts[0]) / (SETPOINTS[-1] - SETPOINTS[0])
        result = {
            "instrument": identity.split(",")[1],
            "pv_prefix": "MOCK:",
            "bias_setpoints_v": SETPOINTS,
            "bias_readbacks_v": readbacks,
            "detector_counts": counts,
            "count_slope_per_v": slope,
            "snapshot": {
                "MOCK:BIAS:SP": SETPOINTS[-1],
                "MOCK:BIAS:RBV": readbacks[-1],
                "MOCK:DETECTOR:COUNT": counts[-1],
            },
            "monitor_history": history,
        }
        Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        client.close()
