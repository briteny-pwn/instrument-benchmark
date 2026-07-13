"""Negative fixture: opens and queries but does not close handle or socket."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path


def _request(file, payload: dict) -> dict:
    file.write((json.dumps(payload) + "\n").encode("utf-8"))
    file.flush()
    return json.loads(file.readline().decode("utf-8"))


def run_experiment(output_path: str) -> dict:
    sock = socket.create_connection((os.environ["INSTRUMENT_SIM_HOST"], int(os.environ["INSTRUMENT_SIM_PORT"])))
    file = sock.makefile("rwb")
    handle = _request(
        file,
        {
            "op": "open",
            "resource": "USB0::0x9999::0x0001::DP100001::INSTR",
            "timeout": 5000,
        },
    )["handle"]
    idn = _request(file, {"op": "query", "handle": handle, "command": "*IDN?"})["response"]
    result = {
        "instrument": idn.split(",")[1],
        "channel": 1,
        "target_voltage_v": 3.3,
        "current_limit_a": 0.5,
        "measured_voltage_v": 0.0,
        "output_enabled": False,
    }
    Path(output_path).write_text(json.dumps(result), encoding="utf-8")
    return result
