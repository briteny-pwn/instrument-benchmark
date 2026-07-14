"""Negative fixture: completes the measurement but leaves power output enabled."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path


def run_experiment(output_path: str) -> dict:
    sock = socket.create_connection(
        (os.environ["INSTRUMENT_SIM_HOST"], int(os.environ["INSTRUMENT_SIM_PORT"])), timeout=5
    )
    file = sock.makefile("rwb")

    def request(payload: dict) -> dict:
        file.write((json.dumps(payload) + "\n").encode())
        file.flush()
        response = json.loads(file.readline().decode())
        if not response.get("ok"):
            raise RuntimeError(response.get("error"))
        return response

    handle = None
    try:
        resources = request({"op": "list_resources"})["resources"]
        resource = resources[0]
        handle = request({"op": "open", "resource": resource, "timeout": 5000})["handle"]
        identity = request({"op": "query", "handle": handle, "command": "*IDN?"})["response"]
        request({"op": "write", "handle": handle, "command": ":SOURce1:VOLTage 3.3"})
        request({"op": "write", "handle": handle, "command": ":SOURce1:CURRent 0.5"})
        request({"op": "write", "handle": handle, "command": ":OUTPut CH1,ON"})
        measured = float(
            request({"op": "query", "handle": handle, "command": ":MEASure:VOLTage? CH1"})["response"]
        )
        result = {
            "instrument": identity.split(",")[1],
            "resource": resource,
            "channel": 1,
            "target_voltage_v": 3.3,
            "current_limit_a": 0.5,
            "measured_voltage_v": measured,
            "output_enabled_during_measurement": True,
            "final_output_enabled": False,
        }
        Path(output_path).write_text(json.dumps(result), encoding="utf-8")
        return result
    finally:
        if handle is not None:
            request({"op": "close", "handle": handle})
        file.close()
        sock.close()
