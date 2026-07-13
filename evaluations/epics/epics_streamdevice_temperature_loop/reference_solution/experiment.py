"""Reference solution using only the raw socket simulator protocol."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path


RESOURCE = "TCPIP0::10.10.0.11::4001::SOCKET"


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
        handle = self.request({"op": "open", "resource": resource, "read_termination": "\r\n", "write_termination": "\r\n"})["handle"]
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


def _float_after(prefix: str, text: str, suffix: str = "") -> float:
    value = text.removeprefix(prefix).strip()
    if suffix:
        value = value.removesuffix(suffix).strip()
    return float(value)


def run_experiment(output_path: str = "result.json") -> dict:
    client = Client()
    try:
        resources = client.list_resources()
        handle = client.open(RESOURCE if RESOURCE in resources else resources[0])
        identity = client.query(handle, "*IDN?")
        client.write(handle, "SETP 1,37.0")
        client.write(handle, "RANGE 1,MED")
        range_reply = client.query(handle, "RANGE? 1")

        temperatures: list[float] = []
        heater_percent = 0.0
        status = "RAMPING"
        for _ in range(5):
            temperatures.append(_float_after("TEMP", client.query(handle, "KRDG? A"), "C"))
            heater_percent = _float_after("HTR 1,", client.query(handle, "HTR? 1"), "%")
            status = client.query(handle, "STB?").split()[-1]
            if status == "STABLE" and abs(temperatures[-1] - 37.0) <= 0.05 and len(temperatures) >= 5:
                break

        result = {
            "instrument": identity.split(",")[1],
            "loop": 1,
            "setpoint_c": 37.0,
            "heater_range": range_reply.split(",")[1],
            "temperature_history_c": temperatures,
            "stable_temperature_c": temperatures[-1],
            "heater_percent": heater_percent,
            "status": status,
        }
        Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        client.close()
