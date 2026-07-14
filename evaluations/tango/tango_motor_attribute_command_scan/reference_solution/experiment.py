"""Reference solution using only the raw socket simulator protocol."""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path


RESOURCE = "TANGO://motor/axis/1"
POSITIONS = [0.0, 1.5, -0.5]


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

    def write(self, handle: str, command: str) -> None:
        self.request({"op": "write", "handle": handle, "command": command})

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
        resources = client.list_resources()
        handle = client.open(RESOURCE if RESOURCE in resources else resources[0])
        info = client.query(handle, "COMMAND info").split()
        client.query(handle, "COMMAND On")
        client.write(handle, "WRITE_ATTR velocity 2.0")
        velocity = _value(client.query(handle, "READ_ATTR velocity"))
        readbacks: list[float] = []
        final_state = "UNKNOWN"
        for target in POSITIONS:
            client.query(handle, f"COMMAND Move {target:.1f}")
            for _ in range(4):
                final_state = client.query(handle, "COMMAND State")
                if final_state == "ON":
                    break
                time.sleep(0.01)
            readbacks.append(_value(client.query(handle, "READ_ATTR position")))
        client.query(handle, "COMMAND Stop")
        max_abs_error = max(abs(target - readback) for target, readback in zip(POSITIONS, readbacks))
        result = {
            "device": info[-1],
            "class": info[1],
            "velocity_mm_s": velocity,
            "target_positions_mm": POSITIONS,
            "readback_positions_mm": readbacks,
            "max_abs_error_mm": max_abs_error,
            "final_state": final_state,
            "stopped": True,
        }
        Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        client.close()
