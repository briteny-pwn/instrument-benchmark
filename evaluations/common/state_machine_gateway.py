"""JSON-line socket gateway backed by standard-library state machines."""

from __future__ import annotations

import base64
import json
import socketserver
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import raw_trace


class Gateway:
    def __init__(self, scenario_path: Path) -> None:
        self.scenario_path = scenario_path.resolve()
        self.scenario = json.loads(self.scenario_path.read_text(encoding="utf-8"))
        self.resource_defs = {item["name"]: item for item in self.scenario.get("resources", [])}
        self.resources: dict[str, dict[str, Any]] = {}
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
        raw_trace.record("gateway_start", {"host": host, "port": port, "backend": str(self.scenario_path)})
        return str(host), int(port)

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        self.resources.clear()
        raw_trace.record("gateway_stop", {})

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        op = request.get("op")
        raw_trace.record("request", request)
        if op == "list_resources":
            resources = list(self.resource_defs)
            raw_trace.record("list_resources", {"resources": resources})
            return {"ok": True, "resources": resources}
        if op == "open":
            resource_name = str(request["resource"])
            if resource_name not in self.resource_defs:
                return {"ok": False, "error": f"Unknown resource: {resource_name}"}
            self.handle_counter += 1
            handle = f"h{self.handle_counter}"
            self.resources[handle] = {
                "name": resource_name,
                "definition": deepcopy(self.resource_defs[resource_name]),
                "counters": {},
            }
            raw_trace.record(
                "open",
                {
                    "handle": handle,
                    "resource": resource_name,
                    "timeout": int(request.get("timeout", 10000)),
                    "read_termination": request.get("read_termination", "\n"),
                    "write_termination": request.get("write_termination", "\n"),
                },
            )
            return {"ok": True, "handle": handle}
        if op == "write":
            handle = str(request["handle"])
            command = str(request["command"])
            self._dispatch_command(handle, "write", command)
            raw_trace.record("write", {"handle": handle, "command": command})
            return {"ok": True}
        if op in {"query", "query_raw"}:
            handle = str(request["handle"])
            command = str(request["command"])
            response = self._dispatch_command(handle, "query", command)
            raw_trace.record("query" if op == "query" else "query_raw", {"handle": handle, "command": command, "response": response})
            if isinstance(response, dict) and response.get("encoding") == "base64":
                return {"ok": True, "encoding": "base64", "data": response["data"]}
            if op == "query_raw":
                data = str(response).encode("latin-1")
                return {"ok": True, "encoding": "base64", "data": base64.b64encode(data).decode("ascii")}
            return {"ok": True, "response": str(response)}
        if op == "close":
            handle = str(request["handle"])
            self.resources.pop(handle, None)
            raw_trace.record("close", {"handle": handle})
            return {"ok": True}
        return {"ok": False, "error": f"Unsupported operation: {op!r}"}

    def _dispatch_command(self, handle: str, kind: str, command: str) -> Any:
        if handle not in self.resources:
            raise RuntimeError(f"Unknown handle: {handle}")
        entry = self.resources[handle]
        normalized = _normalize(command)
        commands = entry["definition"].get("commands", [])
        for rule in commands:
            if rule.get("kind", "query") == kind and _normalize(rule["command"]) == normalized:
                return self._rule_response(entry, rule)
        raise RuntimeError(f"Unsupported {kind} command for {entry['name']}: {command}")

    def _rule_response(self, entry: dict[str, Any], rule: dict[str, Any]) -> Any:
        key = f"{rule.get('kind', 'query')}:{_normalize(rule['command'])}"
        counters = entry["counters"]
        index = counters.get(key, 0)
        counters[key] = index + 1
        if "responses" in rule:
            responses = rule["responses"]
            return responses[min(index, len(responses) - 1)]
        if "base64_data" in rule:
            return {"encoding": "base64", "data": rule["base64_data"]}
        return rule.get("response", "OK")


def _normalize(command: str) -> str:
    return " ".join(str(command).strip().upper().split())
