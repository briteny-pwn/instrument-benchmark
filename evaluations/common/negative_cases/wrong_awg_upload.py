"""Negative fixture: uploads one wrong AWG point but reports the requested waveform."""

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
    output_enabled = False
    try:
        resource = request({"op": "list_resources"})["resources"][0]
        handle = request({"op": "open", "resource": resource, "timeout": 6000})["handle"]
        identity = request({"op": "query", "handle": handle, "command": "*IDN?"})["response"]
        for command in (
            "*RST",
            "DATA:ARB RAMP,0,0.25,0.5,0.75,0.9",
            "FUNC:ARB RAMP",
            "VOLT 2",
            "FREQ 1000",
            "OUTP ON",
        ):
            request({"op": "write", "handle": handle, "command": command})
        output_enabled = True
        observed = request({"op": "query", "handle": handle, "command": "OUTP?"})["response"]
        request({"op": "write", "handle": handle, "command": "OUTP OFF"})
        output_enabled = False
        requested_points = [0.0, 0.25, 0.5, 0.75, 1.0]
        result = {
            "instrument": identity.split(",")[1],
            "resource": resource,
            "waveform": "RAMP",
            "points": requested_points,
            "point_count": 5,
            "amplitude_vpp": 2.0,
            "frequency_hz": 1000.0,
            "output_enabled_during_verification": observed.strip().upper() == "ON",
            "final_output_enabled": False,
        }
        Path(output_path).write_text(json.dumps(result), encoding="utf-8")
        return result
    finally:
        if handle is not None and output_enabled:
            request({"op": "write", "handle": handle, "command": "OUTP OFF"})
        if handle is not None:
            request({"op": "close", "handle": handle})
        file.close()
        sock.close()
