"""Reference solution using only the raw socket simulator protocol."""

from __future__ import annotations

import base64
import json
import os
import socket
from pathlib import Path


AWG_POINTS = [-0.5, -0.25, 0.0, 0.25, 0.5]
TARGETS = {"MockAWG700": "awg", "MockScope900": "scope", "MockDMM650": "dmm"}


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
        handle = self.request({"op": "open", "resource": resource, "timeout": 12000})["handle"]
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
            if len(handles) == len(TARGETS):
                break

        awg = handles["awg"]
        client.write(awg, "*RST")
        client.write(awg, "DATA:ARB CAL_RAMP," + ",".join(f"{point:.6f}" for point in AWG_POINTS))
        client.write(awg, "FUNC:ARB CAL_RAMP")
        client.write(awg, "VOLT 1.2")
        client.write(awg, "VOLT:OFFS 0.0")
        client.write(awg, "OUTP ON")
        output_enabled = client.query(awg, "OUTP?")["response"].strip().upper() in {"1", "ON", "TRUE"}

        dmm = handles["dmm"]
        client.write(dmm, "*RST")
        client.write(dmm, "CONF:VOLT:DC")
        client.write(dmm, "VOLT:RANG 10")
        client.write(dmm, "SAMP:COUN 4")
        client.write(dmm, "INIT")
        dmm_samples = [float(item) for item in client.query(dmm, "READ:VOLT?")["response"].strip().split(";")]

        scope = handles["scope"]
        client.write(scope, "*RST")
        client.write(scope, "DATA:SOURCE CH1")
        client.write(scope, "DATA:ENCODING RIBINARY")
        client.write(scope, "DATA:WIDTH 1")
        client.write(scope, "WFMOUTPRE:YMULT 0.02")
        client.write(scope, "WFMOUTPRE:YOFF 80")
        client.write(scope, "WFMOUTPRE:YZERO 0.0")
        raw_codes = parse_block(client.query(scope, "CURVE?")["data"])
        scope_voltages = [(code - 80) * 0.02 for code in raw_codes]

        dmm_average = sum(dmm_samples) / len(dmm_samples)
        p2p = max(scope_voltages) - min(scope_voltages)
        result = {
            "instruments": identities,
            "resources": resources,
            "awg_waveform": "CAL_RAMP",
            "awg_points": AWG_POINTS,
            "dmm_samples_v": dmm_samples,
            "dmm_average_v": dmm_average,
            "scope_raw_codes": raw_codes,
            "scope_voltages_v": scope_voltages,
            "scope_peak_to_peak_v": p2p,
            "calibration_passed": output_enabled and abs(dmm_average - 1.1995) <= 0.002 and abs(p2p - 1.2) <= 0.02,
        }
        client.write(awg, "OUTP OFF")
        result["final_awg_output_enabled"] = False
        if output_path:
            Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        awg_handle = locals().get("handles", {}).get("awg")
        if awg_handle in client.handles:
            try:
                client.write(awg_handle, "OUTP OFF")
            except Exception:
                pass
        client.close()
