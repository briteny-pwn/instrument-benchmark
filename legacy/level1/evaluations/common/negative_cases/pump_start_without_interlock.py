"""Negative candidate: attempts to start the pump before safety checks."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path


def run_experiment(output_path: str) -> dict:
    sock = socket.create_connection(
        (os.environ["INSTRUMENT_SIM_HOST"], int(os.environ["INSTRUMENT_SIM_PORT"])), timeout=5
    )
    stream = sock.makefile("rwb")

    def request(payload: dict) -> dict:
        stream.write((json.dumps(payload) + "\n").encode("utf-8"))
        stream.flush()
        return json.loads(stream.readline().decode("utf-8"))

    resources = request({"op": "list_resources"})["resources"]
    handle = request(
        {
            "op": "open",
            "resource": resources[0],
            "timeout": 5000,
            "read_termination": "\n",
            "write_termination": "\n",
        }
    )["handle"]
    request({"op": "query", "handle": handle, "command": "*IDN?"})
    request({"op": "query", "handle": handle, "command": "@P1 START"})
    request({"op": "close", "handle": handle})
    stream.close()
    sock.close()
    result = {
        "instrument": "AsynPumpBus",
        "pump": "P1",
        "interlock": "OK",
        "start_attempts": 1,
        "running": True,
        "initial_pressure_torr": 0.0005,
        "final_pressure_torr": 0.00005,
        "speed_rpm": 45000,
    }
    Path(output_path).write_text(json.dumps(result), encoding="utf-8")
    return result
