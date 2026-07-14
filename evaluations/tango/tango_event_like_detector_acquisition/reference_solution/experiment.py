"""Reference solution using only the raw socket simulator protocol."""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path


RESOURCE = "TANGO://detector/sim/1"


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


def _frame(reply: str) -> tuple[int, float]:
    parts = reply.split()
    return int(parts[1]), float(parts[3])


def _last_number(reply: str) -> float:
    return float(reply.split()[-1])


def run_experiment(output_path: str = "result.json") -> dict:
    client = Client()
    try:
        resources = client.list_resources()
        handle = client.open(RESOURCE if RESOURCE in resources else resources[0])
        info = client.query(handle, "COMMAND info").split()
        client.write(handle, "WRITE_ATTR exposure 0.05")
        client.query(handle, "COMMAND StartAcquisition 4")
        frames: list[int] = []
        intensities: list[float] = []
        for _ in range(4):
            frame, intensity = _frame(client.query(handle, "READ_EVENT frame"))
            frames.append(frame)
            intensities.append(intensity)
        final_state = "RUNNING"
        for _ in range(2):
            final_state = client.query(handle, "COMMAND State")
            if final_state == "ON":
                break
            time.sleep(0.01)
        frame_count = int(_last_number(client.query(handle, "READ_ATTR frame_count")))
        mean_intensity = _last_number(client.query(handle, "READ_ATTR mean_intensity"))
        result = {
            "device": info[-1],
            "class": info[1],
            "exposure_s": 0.05,
            "frames": frames,
            "intensities": intensities,
            "frame_count": frame_count,
            "mean_intensity": mean_intensity,
            "final_state": final_state,
        }
        Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        client.close()
