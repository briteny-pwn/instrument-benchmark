"""Reference solution using only the raw socket simulator protocol."""

from __future__ import annotations

import base64
import json
import os
import socket
from pathlib import Path


RESOURCE = "TCPIP0::192.0.2.50::inst0::INSTR"


class RawInstrumentClient:
    def __init__(self) -> None:
        self.sock = socket.create_connection((os.environ["INSTRUMENT_SIM_HOST"], int(os.environ["INSTRUMENT_SIM_PORT"])), timeout=5)
        self.file = self.sock.makefile("rwb")
        self.handles: list[str] = []

    def request(self, payload: dict) -> dict:
        self.file.write((json.dumps(payload) + "\n").encode("utf-8"))
        self.file.flush()
        response = json.loads(self.file.readline().decode("utf-8"))
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "raw simulator error"))
        return response

    def open(self, resource: str) -> str:
        handle = self.request({"op": "open", "resource": resource, "timeout": 8000})["handle"]
        self.handles.append(handle)
        return handle

    def write(self, handle: str, command: str) -> None:
        self.request({"op": "write", "handle": handle, "command": command})

    def query(self, handle: str, command: str) -> dict:
        return self.request({"op": "query", "handle": handle, "command": command})

    def close(self) -> None:
        for handle in list(self.handles):
            self.request({"op": "close", "handle": handle})
        self.file.close()
        self.sock.close()


def parse_ieee_block(encoded: str) -> list[int]:
    data = base64.b64decode(encoded)
    digits = int(chr(data[1]))
    length = int(data[2 : 2 + digits].decode("ascii"))
    payload = data[2 + digits : 2 + digits + length]
    return list(payload)


def run_experiment(output_path: str = "result.json") -> dict:
    client = RawInstrumentClient()
    try:
        handle = client.open(RESOURCE)
        identity = client.query(handle, "*IDN?")["response"].strip()
        client.write(handle, "*RST")
        client.write(handle, "DATA:SOURCE CH1")
        client.write(handle, "DATA:ENCODING RIBINARY")
        client.write(handle, "DATA:WIDTH 1")
        raw_codes = parse_ieee_block(client.query(handle, "CURVE?")["data"])
        voltages = [(code - 128) * 0.02 for code in raw_codes]
        result = {
            "instrument": identity.split(",")[1],
            "source": "CH1",
            "sample_count": len(raw_codes),
            "raw_codes": raw_codes,
            "voltage_scale_v": 0.02,
            "voltage_offset_code": 128,
            "voltages_v": voltages,
            "unit": "V",
        }
        if output_path:
            Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        client.close()

