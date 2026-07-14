"""Negative fixture: queries CURVE? but reports a fixed nominal waveform."""

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
        handle = request({"op": "open", "resource": resource, "timeout": 8000})["handle"]
        identity = request({"op": "query", "handle": handle, "command": "*IDN?"})["response"]
        for command in (
            "*RST",
            "DATA:SOURCE CH1",
            "DATA:ENCODING RIBINARY",
            "DATA:WIDTH 1",
            "WFMOUTPRE:YMULT 0.02",
            "WFMOUTPRE:YOFF 128",
        ):
            request({"op": "write", "handle": handle, "command": command})
        request({"op": "query", "handle": handle, "command": "CURVE?"})
        raw_codes = [65, 66, 67, 68, 69, 70, 49, 50]
        voltages = [(code - 128) * 0.02 for code in raw_codes]
        result = {
            "instrument": identity.strip().split(",")[1],
            "resource": resource,
            "source": "CH1",
            "sample_count": len(raw_codes),
            "raw_codes": raw_codes,
            "voltage_scale_v": 0.02,
            "voltage_offset_code": 128,
            "voltages_v": voltages,
            "mean_voltage_v": sum(voltages) / len(voltages),
            "peak_to_peak_v": max(voltages) - min(voltages),
            "unit": "V",
        }
        Path(output_path).write_text(json.dumps(result), encoding="utf-8")
        return result
    finally:
        if handle is not None:
            request({"op": "close", "handle": handle})
        file.close()
        sock.close()
