"""Negative fixture: varies query labels but never applies the source sweep."""

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
    handles: dict[str, str] = {}

    def request(payload: dict) -> dict:
        file.write((json.dumps(payload) + "\n").encode())
        file.flush()
        response = json.loads(file.readline().decode())
        if not response.get("ok"):
            raise RuntimeError(response.get("error"))
        return response

    try:
        roles: dict[str, str] = {}
        resources_by_role: dict[str, str] = {}
        for resource in request({"op": "list_resources"})["resources"]:
            handle = request(
                {
                    "op": "open",
                    "resource": resource,
                    "timeout": 5000,
                    "read_termination": "\n",
                    "write_termination": "\n",
                }
            )["handle"]
            model = request({"op": "query", "handle": handle, "command": "*IDN?"})["response"].split(",")[1]
            role = {"MockGateSource": "source", "MockDMM7510": "dmm"}.get(model)
            if role:
                handles[role] = handle
                roles[role] = model
                resources_by_role[role] = resource
            else:
                request({"op": "close", "handle": handle})

        request({"op": "write", "handle": handles["source"], "command": "*RST"})
        request({"op": "write", "handle": handles["dmm"], "command": "*RST"})
        request({"op": "write", "handle": handles["dmm"], "command": "CONF:VOLT:DC"})
        request({"op": "write", "handle": handles["source"], "command": "OUTP ON"})
        setpoints = [-0.1, 0.0, 0.1, 0.2, 0.3]
        for setpoint in setpoints:
            request(
                {
                    "op": "query",
                    "handle": handles["dmm"],
                    "command": f"READ:VOLT? {setpoint:.1f}",
                }
            )

        nominal = [-0.19, 0.01, 0.21, 0.41, 0.61]
        result = {
            "framework": "raw_protocol",
            "instruments": roles,
            "resources": resources_by_role,
            "sweep_setpoints_v": setpoints,
            "measured_voltage_v": nominal,
            "slope": 2.0,
            "intercept": 0.01,
            "validation_passed": True,
            "final_source_output_enabled": False,
        }
        request({"op": "write", "handle": handles["source"], "command": "OUTP OFF"})
        Path(output_path).write_text(json.dumps(result), encoding="utf-8")
        return result
    finally:
        for handle in handles.values():
            request({"op": "close", "handle": handle})
        file.close()
        sock.close()
