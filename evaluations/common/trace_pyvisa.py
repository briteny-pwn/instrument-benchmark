"""Generic PyVISA trace wrapper backed by pyvisa-sim.

The wrapper redirects ``pyvisa.ResourceManager()`` to the configured simulator
backend and records generic PyVISA access evidence. It intentionally avoids
encoding instance-specific SCPI semantics; instance scoring should primarily
judge observed experiment results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pyvisa


TRACE: list["TraceEvent"] = []
_SIM_BACKEND = ""
_ORIGINAL_RESOURCE_MANAGER: Any = None


@dataclass
class TraceEvent:
    kind: str
    payload: dict[str, Any]


def configure(sim_backend: str) -> None:
    global _SIM_BACKEND
    _SIM_BACKEND = sim_backend


def install() -> None:
    global _ORIGINAL_RESOURCE_MANAGER
    if getattr(pyvisa.ResourceManager, "_instrument_benchmark_traced", False):
        return

    _ORIGINAL_RESOURCE_MANAGER = pyvisa.ResourceManager

    class TracedResourceManager:
        _instrument_benchmark_traced = True

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            backend_args = args or (_SIM_BACKEND,)
            self._rm = _ORIGINAL_RESOURCE_MANAGER(*backend_args, **kwargs)
            TRACE.append(TraceEvent("resource_manager", {"backend": str(backend_args[0])}))

        def list_resources(self, *args: Any, **kwargs: Any) -> tuple[str, ...]:
            resources = self._rm.list_resources(*args, **kwargs)
            TRACE.append(
                TraceEvent(
                    "list_resources",
                    {"resources": list(resources), "args": list(args), "kwargs": dict(kwargs)},
                )
            )
            return resources

        def open_resource(self, resource_name: str, *args: Any, **kwargs: Any) -> "TracedResource":
            TRACE.append(
                TraceEvent(
                    "open_resource",
                    {"resource_name": resource_name, "args": list(args), "kwargs": dict(kwargs)},
                )
            )
            resource = self._rm.open_resource(resource_name, *args, **kwargs)
            return TracedResource(resource, resource_name)

        def close(self) -> None:
            TRACE.append(TraceEvent("close_resource_manager", {}))
            self._rm.close()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._rm, name)

    pyvisa.ResourceManager = TracedResourceManager  # type: ignore[assignment]


class TracedResource:
    def __init__(self, resource: Any, resource_name: str) -> None:
        object.__setattr__(self, "_resource", resource)
        object.__setattr__(self, "_resource_name", resource_name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"timeout", "read_termination", "write_termination"}:
            TRACE.append(
                TraceEvent(
                    "set_attribute",
                    {"resource_name": self._resource_name, "name": name, "value": value},
                )
            )
        setattr(self._resource, name, value)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resource, name)

    def write(self, command: str, *args: Any, **kwargs: Any) -> Any:
        TRACE.append(
            TraceEvent(
                "write",
                {"resource_name": self._resource_name, "command": command, "args": list(args), "kwargs": dict(kwargs)},
            )
        )
        return self._resource.write(command, *args, **kwargs)

    def query(self, command: str, *args: Any, **kwargs: Any) -> Any:
        TRACE.append(
            TraceEvent(
                "query",
                {"resource_name": self._resource_name, "command": command, "args": list(args), "kwargs": dict(kwargs)},
            )
        )
        return self._resource.query(command, *args, **kwargs)

    def query_ascii_values(self, command: str, *args: Any, **kwargs: Any) -> Any:
        TRACE.append(
            TraceEvent(
                "query_ascii_values",
                {"resource_name": self._resource_name, "command": command, "args": list(args), "kwargs": dict(kwargs)},
            )
        )
        return self._resource.query_ascii_values(command, *args, **kwargs)

    def query_binary_values(self, command: str, *args: Any, **kwargs: Any) -> Any:
        TRACE.append(
            TraceEvent(
                "query_binary_values",
                {"resource_name": self._resource_name, "command": command, "args": list(args), "kwargs": dict(kwargs)},
            )
        )
        return self._resource.query_binary_values(command, *args, **kwargs)

    def write_ascii_values(self, command: str, values: Any, *args: Any, **kwargs: Any) -> Any:
        values_list = list(values)
        TRACE.append(
            TraceEvent(
                "write_ascii_values",
                {
                    "resource_name": self._resource_name,
                    "command": command,
                    "values": values_list,
                    "args": list(args),
                    "kwargs": dict(kwargs),
                },
            )
        )
        return self._resource.write_ascii_values(command, values_list, *args, **kwargs)

    def write_binary_values(self, command: str, values: Any, *args: Any, **kwargs: Any) -> Any:
        values_list = list(values)
        TRACE.append(
            TraceEvent(
                "write_binary_values",
                {
                    "resource_name": self._resource_name,
                    "command": command,
                    "values": values_list,
                    "args": list(args),
                    "kwargs": dict(kwargs),
                },
            )
        )
        return self._resource.write_binary_values(command, values_list, *args, **kwargs)

    def read_raw(self, *args: Any, **kwargs: Any) -> Any:
        TRACE.append(TraceEvent("read_raw", {"resource_name": self._resource_name, "args": list(args), "kwargs": dict(kwargs)}))
        return self._resource.read_raw(*args, **kwargs)

    def close(self) -> None:
        TRACE.append(TraceEvent("close_resource", {"resource_name": self._resource_name}))
        self._resource.close()


def reset_trace() -> None:
    TRACE.clear()


def serializable_trace() -> list[dict[str, Any]]:
    return [{"kind": event.kind, "payload": event.payload} for event in TRACE]

