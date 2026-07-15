"""Negative fixture: reports calibration data without establishing the source state."""

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
    handles: list[str] = []

    def request(payload: dict, *, require_ok: bool = True) -> dict:
        file.write((json.dumps(payload) + "\n").encode())
        file.flush()
        response = json.loads(file.readline().decode())
        if require_ok and not response.get("ok"):
            raise RuntimeError(response.get("error"))
        return response

    try:
        resources = request({"op": "list_resources"})["resources"]
        roles: dict[str, tuple[str, str]] = {}
        for resource in resources:
            handle = request({"op": "open", "resource": resource, "timeout": 12000})["handle"]
            handles.append(handle)
            identity = request({"op": "query", "handle": handle, "command": "*IDN?"})["response"]
            model = identity.strip().split(",")[1]
            if model in {"MockAWG700", "MockScope900", "MockDMM650"}:
                roles[model] = (resource, handle)

        dmm = roles["MockDMM650"][1]
        for command in ("CONF:VOLT:DC", "VOLT:RANG 10", "SAMP:COUN 4", "INIT"):
            request({"op": "write", "handle": dmm, "command": command})

        # A valid gateway rejects this read because no AWG waveform was configured
        # and its output was never enabled. Ignore that error and forge nominal data.
        request({"op": "query", "handle": dmm, "command": "READ:VOLT?"}, require_ok=False)
        result = {
            "instruments": {"awg": "MockAWG700", "scope": "MockScope900", "dmm": "MockDMM650"},
            "resources": {
                "awg": roles["MockAWG700"][0],
                "scope": roles["MockScope900"][0],
                "dmm": roles["MockDMM650"][0],
            },
            "awg_waveform": "CAL_RAMP",
            "awg_points": [-0.5, -0.25, 0.0, 0.25, 0.5],
            "dmm_samples_v": [1.198, 1.201, 1.2, 1.199],
            "dmm_average_v": 1.1995,
            "scope_raw_codes": [80, 95, 110, 95, 80, 65, 50, 65],
            "scope_voltages_v": [0.0, 0.3, 0.6, 0.3, 0.0, -0.3, -0.6, -0.3],
            "scope_peak_to_peak_v": 1.2,
            "calibration_passed": True,
            "final_awg_output_enabled": False,
        }
        Path(output_path).write_text(json.dumps(result), encoding="utf-8")
        return result
    finally:
        for handle in handles:
            request({"op": "close", "handle": handle}, require_ok=False)
        file.close()
        sock.close()
