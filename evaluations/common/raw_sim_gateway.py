"""JSON-line socket gateway backed by hidden pyvisa-sim instruments."""

from __future__ import annotations

import base64
import json
import socket
import socketserver
import threading
from pathlib import Path
from typing import Any

import pyvisa

from . import raw_trace


class Gateway:
    def __init__(self, sim_path: Path) -> None:
        self.sim_backend = str(sim_path.resolve()) + "@sim"
        self.rm = pyvisa.ResourceManager(self.sim_backend)
        self.resources: dict[str, Any] = {}
        self.handle_counter = 0
        self.server: socketserver.ThreadingTCPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> tuple[str, int]:
        gateway = self

        class Handler(socketserver.StreamRequestHandler):
            def setup(self) -> None:
                super().setup()
                raw_trace.record("socket_connect", {"client": repr(self.client_address)})

            def handle(self) -> None:
                for line in self.rfile:
                    try:
                        request = json.loads(line.decode("utf-8"))
                        response = gateway.dispatch(request)
                    except Exception as exc:  # pragma: no cover - defensive boundary
                        response = {"ok": False, "error": str(exc)}
                    self.wfile.write((json.dumps(response) + "\n").encode("utf-8"))
                    self.wfile.flush()

            def finish(self) -> None:
                raw_trace.record("socket_disconnect", {"client": repr(self.client_address)})
                super().finish()

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server(("127.0.0.1", 0), Handler)
        host, port = self.server.server_address
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        raw_trace.record("gateway_start", {"host": host, "port": port, "backend": self.sim_backend})
        return str(host), int(port)

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        for resource in list(self.resources.values()):
            try:
                resource.close()
            except Exception:
                pass
        self.resources.clear()
        self.rm.close()
        raw_trace.record("gateway_stop", {})

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        op = request.get("op")
        raw_trace.record("request", request)
        if op == "list_resources":
            resources = list(self.rm.list_resources())
            raw_trace.record("list_resources", {"resources": resources})
            return {"ok": True, "resources": resources}
        if op == "open":
            resource_name = str(request["resource"])
            self.handle_counter += 1
            handle = f"h{self.handle_counter}"
            resource = self.rm.open_resource(resource_name)
            resource.timeout = int(request.get("timeout", 10000))
            resource.read_termination = request.get("read_termination", "\n")
            resource.write_termination = request.get("write_termination", "\n")
            self.resources[handle] = resource
            raw_trace.record(
                "open",
                {
                    "handle": handle,
                    "resource": resource_name,
                    "timeout": resource.timeout,
                    "read_termination": resource.read_termination,
                    "write_termination": resource.write_termination,
                },
            )
            return {"ok": True, "handle": handle}
        if op == "write":
            handle = str(request["handle"])
            command = str(request["command"])
            self.resources[handle].write(command)
            raw_trace.record("write", {"handle": handle, "command": command})
            return {"ok": True}
        if op == "query":
            handle = str(request["handle"])
            command = str(request["command"])
            response = self.resources[handle].query(command)
            raw_trace.record("query", {"handle": handle, "command": command, "response": response})
            if _looks_binary_block(response):
                data = response.encode("latin-1")
                return {"ok": True, "encoding": "base64", "data": base64.b64encode(data).decode("ascii")}
            return {"ok": True, "response": response}
        if op == "query_raw":
            handle = str(request["handle"])
            command = str(request["command"])
            resource = self.resources[handle]
            resource.write(command)
            data = resource.read_raw()
            raw_trace.record("query_raw", {"handle": handle, "command": command, "byte_count": len(data)})
            return {"ok": True, "encoding": "base64", "data": base64.b64encode(data).decode("ascii")}
        if op == "close":
            handle = str(request["handle"])
            resource = self.resources.pop(handle, None)
            if resource is not None:
                resource.close()
            raw_trace.record("close", {"handle": handle})
            return {"ok": True}
        return {"ok": False, "error": f"Unsupported operation: {op!r}"}


def _looks_binary_block(response: Any) -> bool:
    return isinstance(response, str) and response.startswith("#") and len(response) >= 3 and response[1].isdigit()

