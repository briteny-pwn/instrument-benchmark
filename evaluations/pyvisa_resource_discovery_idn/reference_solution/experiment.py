"""Reference solution for the PyVISA resource discovery IDN instance."""

from __future__ import annotations

import json
from pathlib import Path

import pyvisa


TARGET_MODEL = "MockLogger300"


class ResourceDiscoveryLogger:
    def __init__(self) -> None:
        self.rm = pyvisa.ResourceManager()
        self.opened = []
        self.selected_resource = None
        self.inst = None

    def _configure(self, inst) -> None:
        inst.timeout = 4000
        inst.read_termination = "\n"
        inst.write_termination = "\n"

    def discover(self) -> str:
        for resource_name in self.rm.list_resources():
            inst = self.rm.open_resource(resource_name)
            self.opened.append(inst)
            self._configure(inst)
            identity = inst.query("*IDN?").strip()
            fields = identity.split(",")
            if len(fields) > 1 and fields[1] == TARGET_MODEL:
                self.selected_resource = resource_name
                self.inst = inst
                return identity
        raise RuntimeError(f"Could not find {TARGET_MODEL}")

    def read_environment(self) -> tuple[float, float]:
        self.inst.write("*RST")
        self.inst.write("SENS:CHAN A")
        temperature = float(self.inst.query("MEAS:TEMP? A"))
        humidity = float(self.inst.query("MEAS:HUM? A"))
        return temperature, humidity

    def close(self) -> None:
        for inst in self.opened:
            inst.close()
        self.rm.close()


def run_experiment(output_path: str = "result.json") -> dict:
    logger = ResourceDiscoveryLogger()
    try:
        identity = logger.discover()
        temperature, humidity = logger.read_environment()
        result = {
            "instrument": identity.split(",")[1],
            "selected_resource": logger.selected_resource,
            "channel": "A",
            "temperature_c": temperature,
            "relative_humidity_percent": humidity,
        }
        if output_path:
            Path(output_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        logger.close()

