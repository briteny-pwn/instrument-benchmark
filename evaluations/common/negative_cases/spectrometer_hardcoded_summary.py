"""Negative candidate: performs acquisition but ignores the returned arrays."""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path


def run_experiment(output_path: str) -> dict:
    sock = socket.create_connection(
        (os.environ["INSTRUMENT_SIM_HOST"], int(os.environ["INSTRUMENT_SIM_PORT"])), timeout=5
    )
    stream = sock.makefile("rwb")

    def request(payload: dict) -> dict:
        stream.write((json.dumps(payload) + "\n").encode("utf-8"))
        stream.flush()
        response = json.loads(stream.readline().decode("utf-8"))
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "simulator error"))
        return response

    resource = request({"op": "list_resources"})["resources"][0]
    handle = request(
        {
            "op": "open",
            "resource": resource,
            "timeout": 5000,
            "read_termination": "\n",
            "write_termination": "\n",
        }
    )["handle"]
    request({"op": "query", "handle": handle, "command": "*IDN?"})
    request({"op": "query", "handle": handle, "command": "STATE?"})
    request({"op": "write", "handle": handle, "command": "SET_CENTER 550.0"})
    request({"op": "query", "handle": handle, "command": "CENTER?"})
    request({"op": "query", "handle": handle, "command": "MEASURE"})
    for _ in range(100):
        if request({"op": "query", "handle": handle, "command": "BUSY?"})["response"] == "FALSE":
            break
        time.sleep(0.01)
    request({"op": "query", "handle": handle, "command": "WAVELENGTHS?"})
    request({"op": "query", "handle": handle, "command": "COUNTS?"})
    request({"op": "close", "handle": handle})
    stream.close()
    sock.close()
    result = {
        "instrument": "fake-spectrometer",
        "resource": resource,
        "central_wavelength_nm": 550.0,
        "point_count": 551,
        "peak_wavelength_nm": 550.0,
        "peak_counts": 110.0,
        "integrated_counts": 15000.0,
        "completed": True,
    }
    Path(output_path).write_text(json.dumps(result), encoding="utf-8")
    return result
