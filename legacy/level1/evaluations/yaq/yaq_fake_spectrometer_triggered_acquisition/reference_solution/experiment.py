from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path


class RawClient:
    def __init__(self) -> None:
        self.sock = socket.create_connection((os.environ["INSTRUMENT_SIM_HOST"], int(os.environ["INSTRUMENT_SIM_PORT"])), timeout=5)
        self.file = self.sock.makefile("rwb")

    def request(self, payload: dict) -> dict:
        self.file.write((json.dumps(payload) + "\n").encode("utf-8"))
        self.file.flush()
        response = json.loads(self.file.readline().decode("utf-8"))
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "simulator request failed"))
        return response

    def close(self) -> None:
        self.file.close()
        self.sock.close()


def _array(response: str, prefix: str) -> list[float]:
    if not response.startswith(prefix + " "):
        raise RuntimeError(f"unexpected array response: {response[:60]}")
    return [float(item) for item in response[len(prefix) + 1 :].split(",") if item]


def run_experiment(output_path: str) -> dict:
    client = RawClient()
    handle = None
    try:
        resources = client.request({"op": "list_resources"})["resources"]
        resource = ""
        identity = ""
        for candidate_resource in resources:
            candidate_handle = client.request(
                {
                    "op": "open",
                    "resource": candidate_resource,
                    "timeout": 5000,
                    "read_termination": "\n",
                    "write_termination": "\n",
                }
            )["handle"]
            candidate_identity = client.request(
                {"op": "query", "handle": candidate_handle, "command": "*IDN?"}
            )["response"]
            if ",fake-spectrometer," in candidate_identity:
                resource, handle, identity = candidate_resource, candidate_handle, candidate_identity
                break
            client.request({"op": "close", "handle": candidate_handle})
        if handle is None:
            raise RuntimeError("spectrometer resource not found")
        client.request({"op": "query", "handle": handle, "command": "STATE?"})
        client.request({"op": "write", "handle": handle, "command": "SET_CENTER 550.0"})
        center = float(client.request({"op": "query", "handle": handle, "command": "CENTER?"})["response"].split()[1])
        client.request({"op": "query", "handle": handle, "command": "MEASURE"})
        for _ in range(100):
            busy = client.request({"op": "query", "handle": handle, "command": "BUSY?"})["response"]
            if busy == "FALSE":
                break
            time.sleep(0.02)
        wavelengths = _array(client.request({"op": "query", "handle": handle, "command": "WAVELENGTHS?"})["response"], "WAVELENGTHS")
        counts = _array(client.request({"op": "query", "handle": handle, "command": "COUNTS?"})["response"], "COUNTS")
        peak_index = max(range(len(counts)), key=lambda index: counts[index])
        result = {
            "instrument": identity.split(",")[1],
            "resource": resource,
            "central_wavelength_nm": center,
            "point_count": len(counts),
            "peak_wavelength_nm": wavelengths[peak_index],
            "peak_counts": counts[peak_index],
            "integrated_counts": sum(counts),
            "completed": True,
        }
        Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        if handle is not None:
            client.request({"op": "close", "handle": handle})
        client.close()
