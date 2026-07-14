from __future__ import annotations

import json
import os
import socket
import statistics
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


def _parse_measurement(response: str) -> float:
    parts = response.split()
    return float(parts[2])


def run_experiment(output_path: str) -> dict:
    client = RawClient()
    handle = None
    try:
        resources = client.request({"op": "list_resources"})["resources"]
        resource = None
        identity = None
        for candidate in resources:
            candidate_handle = client.request({"op": "open", "resource": candidate, "timeout": 5000})["handle"]
            candidate_identity = client.request({"op": "query", "handle": candidate_handle, "command": "*IDN?"})["response"]
            if candidate_identity.split(",")[1] == "fake-sensor":
                resource = candidate
                handle = candidate_handle
                identity = candidate_identity
                break
            client.request({"op": "close", "handle": candidate_handle})
        if resource is None or identity is None:
            raise RuntimeError("sensor resource not found")
        client.request({"op": "query", "handle": handle, "command": "STATE?"})
        channels = client.request({"op": "query", "handle": handle, "command": "CHANNELS?"})["response"].split(",")
        if "signal" not in channels:
            raise RuntimeError("signal channel missing")
        samples = []
        for _ in range(5):
            samples.append(_parse_measurement(client.request({"op": "query", "handle": handle, "command": "MEASURE? signal"})["response"]))
            time.sleep(0.06)
        client.request({"op": "query", "handle": handle, "command": "BUSY?"})
        std_signal = statistics.stdev(samples)
        result = {
            "instrument": identity.split(",")[1],
            "resource": resource,
            "channel": "signal",
            "sample_count": len(samples),
            "mean_signal": statistics.mean(samples),
            "std_signal": std_signal,
            "stable": std_signal < 0.01,
        }
        Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        if handle is not None:
            client.request({"op": "close", "handle": handle})
        client.close()
