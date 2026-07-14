"""Reference solution using only the raw socket simulator protocol."""

from __future__ import annotations

import base64
import json
import os
import socket
from pathlib import Path


AWG_POINTS = [0.0, 0.3, 0.6, 0.9, 1.2, 0.9, 0.6, 0.3]
TARGETS = {
    "MockPSU320": "psu",
    "MockSwitch48": "switch",
    "MockAWG900": "awg",
    "MockScope1200": "scope",
    "MockDMM7510": "dmm",
}


class RawInstrumentClient:
    def __init__(self) -> None:
        self.sock = socket.create_connection((os.environ["INSTRUMENT_SIM_HOST"], int(os.environ["INSTRUMENT_SIM_PORT"])), timeout=5)
        self.file = self.sock.makefile("rwb")
        self.handles: dict[str, str] = {}

    def request(self, payload: dict) -> dict:
        self.file.write((json.dumps(payload) + "\n").encode("utf-8"))
        self.file.flush()
        response = json.loads(self.file.readline().decode("utf-8"))
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "raw simulator error"))
        return response

    def list_resources(self) -> list[str]:
        return self.request({"op": "list_resources"})["resources"]

    def open(self, resource: str) -> str:
        handle = self.request({"op": "open", "resource": resource, "timeout": 15000})["handle"]
        self.handles[handle] = resource
        return handle

    def write(self, handle: str, command: str) -> None:
        self.request({"op": "write", "handle": handle, "command": command})

    def query(self, handle: str, command: str) -> dict:
        return self.request({"op": "query", "handle": handle, "command": command})

    def close_handle(self, handle: str) -> None:
        self.request({"op": "close", "handle": handle})
        self.handles.pop(handle, None)

    def close(self) -> None:
        for handle in list(self.handles):
            self.close_handle(handle)
        self.file.close()
        self.sock.close()


def parse_block(encoded: str) -> list[int]:
    data = base64.b64decode(encoded)
    digits = int(chr(data[1]))
    length = int(data[2 : 2 + digits].decode("ascii"))
    return list(data[2 + digits : 2 + digits + length])


def run_experiment(output_path: str = "result.json") -> dict:
    client = RawInstrumentClient()
    try:
        handles: dict[str, str] = {}
        identities: dict[str, str] = {}
        resources: dict[str, str] = {}
        for resource in client.list_resources():
            handle = client.open(resource)
            identity = client.query(handle, "*IDN?")["response"].strip()
            model = identity.split(",")[1]
            role = TARGETS.get(model)
            if role:
                handles[role] = handle
                identities[role] = model
                resources[role] = resource
            else:
                client.close_handle(handle)

        psu = handles["psu"]
        client.write(psu, "*RST")
        client.write(psu, ":SOUR:VOLT 5")
        client.write(psu, ":SOUR:CURR 0.2")
        client.write(psu, ":OUTP ON")
        supply_voltage = float(client.query(psu, ":MEAS:VOLT?")["response"])
        supply_enabled = client.query(psu, ":OUTP?")["response"].strip().upper() in {"1", "ON", "TRUE"}

        switch = handles["switch"]
        client.write(switch, "*RST")
        client.write(switch, "ROUT:OPEN:ALL")
        client.write(switch, "ROUT:CLOS (@101,102)")
        closed_paths = client.query(switch, "ROUT:CLOS?")["response"].strip()

        awg = handles["awg"]
        client.write(awg, "*RST")
        client.write(awg, "DATA:ARB DUT_STAIR," + ",".join(f"{point:.6f}" for point in AWG_POINTS))
        client.write(awg, "FUNC:ARB DUT_STAIR")
        client.write(awg, "VOLT 1.2")
        client.write(awg, "VOLT:OFFS 0.0")
        client.write(awg, "FREQ 1000")
        client.write(awg, "OUTP ON")
        awg_enabled = client.query(awg, "OUTP?")["response"].strip().upper() in {"1", "ON", "TRUE"}

        dmm = handles["dmm"]
        client.write(dmm, "*RST")
        client.write(dmm, "CONF:VOLT:DC")
        client.write(dmm, "VOLT:RANG 10")
        client.write(dmm, "SAMP:COUN 8")
        client.write(dmm, "TRIG:SOUR IMM")
        client.write(dmm, "INIT")
        dmm_samples = [float(item) for item in client.query(dmm, "FETCH:VOLT?")["response"].split(",")]

        scope = handles["scope"]
        client.write(scope, "*RST")
        client.write(scope, "DATA:SOURCE CH1")
        client.write(scope, "DATA:ENCODING RIBINARY")
        client.write(scope, "DATA:WIDTH 1")
        client.write(scope, "WFMOUTPRE:YMULT 0.02")
        client.write(scope, "WFMOUTPRE:YOFF 50")
        client.write(scope, "WFMOUTPRE:YZERO 0.0")
        raw_codes = parse_block(client.query(scope, "CURVE?")["data"])
        scope_voltages = [(code - 50) * 0.02 for code in raw_codes]
        p2p = max(scope_voltages) - min(scope_voltages)
        max_error = max(abs(a - b) for a, b in zip(scope_voltages, dmm_samples))

        result = {
            "instruments": identities,
            "resources": resources,
            "supply_voltage_v": supply_voltage,
            "supply_output_enabled": supply_enabled,
            "switch_closed_paths": closed_paths,
            "awg_waveform": "DUT_STAIR",
            "awg_points": AWG_POINTS,
            "awg_output_enabled": awg_enabled,
            "dmm_samples_v": dmm_samples,
            "dmm_average_v": sum(dmm_samples) / len(dmm_samples),
            "scope_raw_codes": raw_codes,
            "scope_voltages_v": scope_voltages,
            "scope_peak_to_peak_v": p2p,
            "max_scope_dmm_error_v": max_error,
            "validation_passed": 4.95 <= supply_voltage <= 5.05 and supply_enabled and closed_paths == "(@101,102)" and awg_enabled and abs(p2p - 1.2) <= 0.02 and max_error <= 0.005,
        }
        client.write(awg, "OUTP OFF")
        client.write(psu, ":OUTP OFF")
        client.write(switch, "ROUT:OPEN:ALL")
        result.update(
            {
                "final_psu_output_enabled": False,
                "final_awg_output_enabled": False,
                "final_switch_closed_paths": "(@)",
            }
        )
        if output_path:
            Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        local_handles = locals().get("handles", {})
        for role, command in (
            ("awg", "OUTP OFF"),
            ("psu", ":OUTP OFF"),
            ("switch", "ROUT:OPEN:ALL"),
        ):
            handle = local_handles.get(role)
            if handle in client.handles:
                try:
                    client.write(handle, command)
                except Exception:
                    pass
        client.close()
