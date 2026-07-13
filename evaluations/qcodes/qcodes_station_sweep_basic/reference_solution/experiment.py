"""Reference solution using only the raw socket simulator protocol."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path


class RawInstrumentClient:
    def __init__(self) -> None:
        host = os.environ["INSTRUMENT_SIM_HOST"]
        port = int(os.environ["INSTRUMENT_SIM_PORT"])
        self.sock = socket.create_connection((host, port), timeout=5)
        self.file = self.sock.makefile("rwb")

    def request(self, payload: dict) -> dict:
        self.file.write((json.dumps(payload) + "\n").encode("utf-8"))
        self.file.flush()
        line = self.file.readline()
        if not line:
            raise RuntimeError("simulator gateway closed the connection")
        response = json.loads(line.decode("utf-8"))
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "gateway request failed"))
        return response

    def list_resources(self) -> list[str]:
        return list(self.request({"op": "list_resources"})["resources"])

    def open(self, resource: str) -> str:
        return str(
            self.request(
                {
                    "op": "open",
                    "resource": resource,
                    "timeout": 5000,
                    "read_termination": "\n",
                    "write_termination": "\n",
                }
            )["handle"]
        )

    def write(self, handle: str, command: str) -> None:
        self.request({"op": "write", "handle": handle, "command": command})

    def query(self, handle: str, command: str) -> str:
        return str(self.request({"op": "query", "handle": handle, "command": command})["response"]).strip()

    def close_handle(self, handle: str) -> None:
        self.request({"op": "close", "handle": handle})

    def close(self) -> None:
        self.file.close()
        self.sock.close()


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = sum((x - mean_x) ** 2 for x in xs)
    slope = numerator / denominator
    intercept = mean_y - slope * mean_x
    return slope, intercept


def run_experiment(output_path: str) -> dict:
    client = RawInstrumentClient()
    source_handle = ""
    dmm_handle = ""
    try:
        resources = client.list_resources()
        source_resource = next(resource for resource in resources if "203.0.113.210" in resource)
        dmm_resource = next(resource for resource in resources if "203.0.113.211" in resource)

        source_handle = client.open(source_resource)
        dmm_handle = client.open(dmm_resource)

        source_idn = client.query(source_handle, "*IDN?")
        dmm_idn = client.query(dmm_handle, "*IDN?")
        client.write(source_handle, "*RST")
        client.write(dmm_handle, "*RST")
        client.write(dmm_handle, "CONF:VOLT:DC")
        client.write(source_handle, "OUTP ON")

        setpoints = [-0.1, 0.0, 0.1, 0.2, 0.3]
        measured: list[float] = []
        for setpoint in setpoints:
            client.write(source_handle, f"SOUR:GATE {setpoint:.1f}")
            measured.append(float(client.query(dmm_handle, f"READ:VOLT? {setpoint:.1f}")))

        slope, intercept = _linear_fit(setpoints, measured)
        result = {
            "framework": "raw_protocol",
            "instruments": {
                "source": source_idn.split(",")[1],
                "dmm": dmm_idn.split(",")[1],
            },
            "resources": {
                "source": source_resource,
                "dmm": dmm_resource,
            },
            "sweep_setpoints_v": setpoints,
            "measured_voltage_v": measured,
            "slope": slope,
            "intercept": intercept,
            "validation_passed": abs(slope - 2.0) < 1e-9 and abs(intercept - 0.01) < 1e-9,
        }
        Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        if source_handle:
            client.close_handle(source_handle)
        if dmm_handle:
            client.close_handle(dmm_handle)
        client.close()
