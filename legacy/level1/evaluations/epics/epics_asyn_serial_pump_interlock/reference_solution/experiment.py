"""Reference solution using only the raw socket simulator protocol."""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path


RESOURCE = "ASYN::SERIAL0::PUMPCTL::INSTR"


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

    def query(self, handle: str, command: str) -> str:
        return self.request({"op": "query", "handle": handle, "command": command})["response"].strip()

    def close(self) -> None:
        for handle in list(self.handles):
            self.request({"op": "close", "handle": handle})
        self.file.close()
        self.sock.close()


def _pressure(reply: str) -> float:
    return float(reply.split()[1])


def run_experiment(output_path: str = "result.json") -> dict:
    client = Client()
    try:
        resources = client.list_resources()
        handle = client.open(RESOURCE if RESOURCE in resources else resources[0])
        identity = client.query(handle, "*IDN?")
        initial_pressure = _pressure(client.query(handle, "@G1 PRES?"))
        interlock = client.query(handle, "@P1 ILK?").split()[1]
        if interlock != "OK" or initial_pressure >= 1.0e-3:
            raise RuntimeError("Pump interlock is not satisfied")

        attempts = 0
        while True:
            attempts += 1
            reply = client.query(handle, "@P1 START")
            if reply == "ACK":
                break
            if reply != "NAK BUSY" or attempts >= 3:
                raise RuntimeError(f"Pump did not start: {reply}")
            time.sleep(0.01)

        running = client.query(handle, "@P1 START?").split()[1] == "1"
        final_pressure = _pressure(client.query(handle, "@G1 PRES?"))
        speed_rpm = int(client.query(handle, "@P1 RPM?").split()[1])
        result = {
            "instrument": identity.split(",")[1],
            "pump": "P1",
            "interlock": interlock,
            "start_attempts": attempts,
            "running": running,
            "initial_pressure_torr": initial_pressure,
            "final_pressure_torr": final_pressure,
            "speed_rpm": speed_rpm,
        }
        Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        client.close()
