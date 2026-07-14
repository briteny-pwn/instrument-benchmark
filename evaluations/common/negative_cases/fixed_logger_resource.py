"""Negative fixture: assumes the nominal logger address and observations."""

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
    handle = None

    def request(payload: dict) -> dict:
        file.write((json.dumps(payload) + "\n").encode())
        file.flush()
        response = json.loads(file.readline().decode())
        if not response.get("ok"):
            raise RuntimeError(response.get("error"))
        return response

    try:
        request({"op": "list_resources"})
        resource = "TCPIP0::198.51.100.30::inst0::INSTR"
        handle = request(
            {
                "op": "open",
                "resource": resource,
                "timeout": 4000,
                "read_termination": "\n",
                "write_termination": "\n",
            }
        )["handle"]
        request({"op": "query", "handle": handle, "command": "*IDN?"})
        request({"op": "write", "handle": handle, "command": "SENS:CHAN A"})
        request({"op": "query", "handle": handle, "command": "MEAS:TEMP? A"})
        request({"op": "query", "handle": handle, "command": "MEAS:HUM? A"})
        result = {
            "instrument": "MockLogger300",
            "selected_resource": resource,
            "channel": "A",
            "temperature_c": 23.45,
            "relative_humidity_percent": 45.6,
        }
        Path(output_path).write_text(json.dumps(result), encoding="utf-8")
        return result
    finally:
        if handle is not None:
            request({"op": "close", "handle": handle})
        file.close()
        sock.close()
