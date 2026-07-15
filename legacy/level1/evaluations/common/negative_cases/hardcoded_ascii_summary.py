"""Negative fixture: performs DMM I/O but reports a fixed nominal data set."""

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
        resource = request({"op": "list_resources"})["resources"][0]
        handle = request({"op": "open", "resource": resource, "timeout": 10000})["handle"]
        identity = request({"op": "query", "handle": handle, "command": "*IDN?"})["response"]
        for command in ("*RST", "CONF:VOLT:DC", "VOLT:RANG 10", "VOLT:RES 0.001", "SAMP:COUN 5", "INIT"):
            request({"op": "write", "handle": handle, "command": command})
        request({"op": "query", "handle": handle, "command": "TRACE:DATA?"})
        request({"op": "write", "handle": handle, "command": "TRACE:CLEAR"})
        samples = [1.001, 1.003, 0.999, 1.002, 1.0]
        result = {
            "instrument": identity.split(",")[1],
            "resource": resource,
            "measurement": "dc_voltage",
            "sample_count": len(samples),
            "samples_v": samples,
            "average_voltage_v": sum(samples) / len(samples),
            "unit": "V",
        }
        Path(output_path).write_text(json.dumps(result), encoding="utf-8")
        return result
    finally:
        if handle is not None:
            request({"op": "close", "handle": handle})
        file.close()
        sock.close()
