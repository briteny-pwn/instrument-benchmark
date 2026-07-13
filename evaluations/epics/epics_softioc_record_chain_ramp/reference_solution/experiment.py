"""Reference solution using only the raw socket simulator protocol."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path


RESOURCE = "IOC::RAMPCHAIN::SIM"
SETPOINTS = [0.0, 1.0, 2.0, 3.0]


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


def _readback(reply: str) -> float:
    return float(reply.split()[1])


def run_experiment(output_path: str = "result.json") -> dict:
    client = Client()
    try:
        resources = client.list_resources()
        handle = client.open(RESOURCE if RESOURCE in resources else resources[0])
        identity = client.query(handle, "*IDN?")
        client.write(handle, "PSU:ENABLE 1")
        readbacks: list[float] = []
        for value in SETPOINTS:
            client.write(handle, f"PSU:SET {value:.1f}")
            readbacks.append(_readback(client.query(handle, f"DMM:READ? {value:.1f}")))
        errors = [round(readback - setpoint, 12) for setpoint, readback in zip(SETPOINTS, readbacks)]
        max_abs_error = max(abs(error) for error in errors)
        result = {
            "instrument": identity.split(",")[1],
            "setpoints_v": SETPOINTS,
            "readbacks_v": readbacks,
            "errors_v": errors,
            "max_abs_error_v": max_abs_error,
            "alarm": "NO_ALARM" if max_abs_error <= 0.05 else "HIGH",
            "processed_records": ["ao:setpoint", "bo:enable", "ai:readback", "calc:error", "bi:alarm"],
        }
        Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        client.close()
