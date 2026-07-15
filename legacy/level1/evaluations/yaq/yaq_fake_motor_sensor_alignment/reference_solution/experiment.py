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


def _value(response: str) -> float:
    return float(response.split()[1])


def run_experiment(output_path: str) -> dict:
    client = RawClient()
    handles: list[str] = []
    motor_handle = sensor_handle = None
    motor_id = sensor_id = ""
    try:
        resources = client.request({"op": "list_resources"})["resources"]
        for resource in resources:
            handle = client.request({"op": "open", "resource": resource, "timeout": 5000, "read_termination": "\n", "write_termination": "\n"})["handle"]
            handles.append(handle)
            identity = client.request({"op": "query", "handle": handle, "command": "*IDN?"})["response"]
            if ",fake-continuous-hardware," in identity:
                motor_handle, motor_id = handle, identity
            elif ",fake-sensor," in identity:
                sensor_handle, sensor_id = handle, identity
        if motor_handle is None or sensor_handle is None:
            raise RuntimeError("alignment resources missing")
        client.request({"op": "query", "handle": motor_handle, "command": "LIMITS?"})
        client.request({"op": "query", "handle": motor_handle, "command": "UNITS?"})
        positions = [-1.0, 0.0, 1.0]
        readbacks = []
        samples = []
        for position in positions:
            client.request({"op": "write", "handle": motor_handle, "command": f"SET_POSITION {position:.1f}"})
            for _ in range(100):
                busy = client.request({"op": "query", "handle": motor_handle, "command": "BUSY?"})["response"]
                if busy == "FALSE":
                    break
                time.sleep(0.02)
            readbacks.append(_value(client.request({"op": "query", "handle": motor_handle, "command": "POSITION?"})["response"]))
            samples.append(float(client.request({"op": "query", "handle": sensor_handle, "command": "MEASURE? alignment"})["response"].split()[2]))
        client.request({"op": "query", "handle": sensor_handle, "command": "BUSY?"})
        result = {
            "motor": motor_id.split(",")[1],
            "sensor": sensor_id.split(",")[1],
            "positions_mm": positions,
            "readbacks_mm": readbacks,
            "sensor_channel": "alignment",
            "sensor_values": samples,
            "sample_count": len(samples),
            "max_abs_error_mm": max(abs(a - b) for a, b in zip(positions, readbacks)),
            "best_position_mm": positions[max(range(len(samples)), key=samples.__getitem__)],
            "completed": True,
        }
        Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        for handle in reversed(handles):
            client.request({"op": "close", "handle": handle})
        client.close()
