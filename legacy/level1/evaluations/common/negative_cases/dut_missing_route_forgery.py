"""Negative fixture: measures with an open signal path and reports nominal data."""

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
    resources_by_role: dict[str, str] = {}
    models = {
        "MockPSU320": "psu",
        "MockSwitch48": "switch",
        "MockAWG900": "awg",
        "MockScope1200": "scope",
        "MockDMM7510": "dmm",
    }

    def request(payload: dict) -> dict:
        file.write((json.dumps(payload) + "\n").encode())
        file.flush()
        response = json.loads(file.readline().decode())
        if not response.get("ok"):
            raise RuntimeError(response.get("error"))
        return response

    try:
        for resource in request({"op": "list_resources"})["resources"]:
            handle = request({"op": "open", "resource": resource, "timeout": 15000})["handle"]
            model = request({"op": "query", "handle": handle, "command": "*IDN?"})["response"].split(",")[1]
            role = models.get(model)
            if role:
                handles[role] = handle
                resources_by_role[role] = resource
            else:
                request({"op": "close", "handle": handle})

        def write(role: str, command: str) -> None:
            request({"op": "write", "handle": handles[role], "command": command})

        def query(role: str, command: str) -> dict:
            return request({"op": "query", "handle": handles[role], "command": command})

        for command in ("*RST", ":SOUR:VOLT 5", ":SOUR:CURR 0.2", ":OUTP ON"):
            write("psu", command)
        supply = float(query("psu", ":MEAS:VOLT?")["response"])
        query("psu", ":OUTP?")

        write("switch", "*RST")
        write("switch", "ROUT:OPEN:ALL")

        for command in (
            "*RST",
            "DATA:ARB DUT_STAIR,0,0.3,0.6,0.9,1.2,0.9,0.6,0.3",
            "FUNC:ARB DUT_STAIR",
            "VOLT 1.2",
            "VOLT:OFFS 0",
            "FREQ 1000",
            "OUTP ON",
        ):
            write("awg", command)
        query("awg", "OUTP?")

        for command in ("*RST", "CONF:VOLT:DC", "VOLT:RANG 10", "SAMP:COUN 8", "TRIG:SOUR IMM", "INIT"):
            write("dmm", command)
        query("dmm", "FETCH:VOLT?")

        for command in (
            "*RST",
            "DATA:SOURCE CH1",
            "DATA:ENCODING RIBINARY",
            "DATA:WIDTH 1",
            "WFMOUTPRE:YMULT 0.02",
            "WFMOUTPRE:YOFF 50",
            "WFMOUTPRE:YZERO 0",
        ):
            write("scope", command)
        query("scope", "CURVE?")

        nominal = [0.0, 0.3, 0.6, 0.9, 1.2, 0.9, 0.6, 0.3]
        raw = [50, 65, 80, 95, 110, 95, 80, 65]
        result = {
            "instruments": {role: model for model, role in models.items()},
            "resources": resources_by_role,
            "supply_voltage_v": supply,
            "supply_output_enabled": True,
            "switch_closed_paths": "(@101,102)",
            "awg_waveform": "DUT_STAIR",
            "awg_points": nominal,
            "awg_output_enabled": True,
            "dmm_samples_v": nominal,
            "dmm_average_v": sum(nominal) / len(nominal),
            "scope_raw_codes": raw,
            "scope_voltages_v": nominal,
            "scope_peak_to_peak_v": 1.2,
            "max_scope_dmm_error_v": 0.0,
            "validation_passed": True,
            "final_psu_output_enabled": False,
            "final_awg_output_enabled": False,
            "final_switch_closed_paths": "(@)",
        }
        write("awg", "OUTP OFF")
        write("psu", ":OUTP OFF")
        write("switch", "ROUT:OPEN:ALL")
        Path(output_path).write_text(json.dumps(result), encoding="utf-8")
        return result
    finally:
        for handle in handles.values():
            request({"op": "close", "handle": handle})
        file.close()
        sock.close()
