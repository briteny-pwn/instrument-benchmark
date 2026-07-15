"""JSON-line socket gateway backed by standard-library state machines."""

from __future__ import annotations

import base64
import json
import re
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
        self.state: dict[str, Any] = deepcopy(self.scenario.get("initial_state", {}))
        self.command_counters: dict[str, int] = {}
        self.handle_counter = 0
        self.server: socketserver.ThreadingTCPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self, host: str = "127.0.0.1", port: int = 0) -> tuple[str, int]:
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

        self.server = Server((host, port), Handler)
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

    def snapshot_state(self) -> dict[str, Any]:
        return {
            "resources": list(self.resource_defs),
            "open_handles": sorted(self.resources),
            "state": deepcopy(self.state),
            "command_counters": dict(self.command_counters),
        }

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
            }
            raw_trace.record(
                "open",
                {
                    "handle": handle,
                    "resource": resource_name,
                    "timeout": int(request.get("timeout", 10000)),
                    "read_termination": request.get("read_termination", "\n"),
                    "write_termination": request.get("write_termination", "\n"),
                    "timeout_explicit": "timeout" in request,
                    "read_termination_explicit": "read_termination" in request,
                    "write_termination_explicit": "write_termination" in request,
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
            match = _match_rule(rule, normalized)
            if rule.get("kind", "query") == kind and match is not None:
                return self._rule_response(entry["name"], rule, match)
        raise RuntimeError(f"Unsupported {kind} command for {entry['name']}: {command}")

    def _rule_response(
        self, resource_name: str, rule: dict[str, Any], command_match: re.Match[str]
    ) -> Any:
        for path, expected in rule.get("requires_state", {}).items():
            actual = _get_state_path(self.state, path)
            if actual != expected:
                raise RuntimeError(
                    f"State precondition failed for {resource_name} {rule['command']}: "
                    f"{path} expected {expected!r}, got {actual!r}"
                )

        rule_identity = rule.get("command_regex", rule.get("command", ""))
        key = f"{resource_name}:{rule.get('kind', 'query')}:{_normalize(rule_identity)}"
        index = self.command_counters.get(key, 0)
        self.command_counters[key] = index + 1
        response: Any
        step: dict[str, Any] = {}
        if "steps" in rule:
            steps = rule["steps"]
            step = steps[min(index, len(steps) - 1)]
            response = step.get("response", "OK")
        elif "responses" in rule:
            responses = rule["responses"]
            response = responses[min(index, len(responses) - 1)]
        elif "base64_data" in rule:
            response = {"encoding": "base64", "data": rule["base64_data"]}
        else:
            response = rule.get("response", "OK")

        updates = {**rule.get("state_updates", {}), **step.get("state_updates", {})}
        for path, value in updates.items():
            _set_state_path(self.state, path, deepcopy(value))
        increments = {**rule.get("state_increments", {}), **step.get("state_increments", {})}
        for path, amount in increments.items():
            current = _get_state_path(self.state, path, 0)
            _set_state_path(self.state, path, current + amount)
        captured_updates = {**rule.get("state_from_groups", {}), **step.get("state_from_groups", {})}
        for path, transform in captured_updates.items():
            _set_state_path(self.state, path, _transform_capture(command_match, transform))
        appends = {**rule.get("state_appends", {}), **step.get("state_appends", {})}
        for path, values in appends.items():
            current = _get_state_path(self.state, path)
            if current is None:
                current = []
                _set_state_path(self.state, path, current)
            if not isinstance(current, list):
                raise RuntimeError(f"Cannot append to non-list state path {path!r}")
            current.extend(deepcopy(values if isinstance(values, list) else [values]))

        if rule.get("response_state"):
            response = _get_state_path(self.state, str(rule["response_state"]))
        if rule.get("response_template"):
            response = _render_state_template(str(rule["response_template"]), self.state)
        return response


def _normalize(command: str) -> str:
    return " ".join(str(command).strip().upper().split())


def _match_rule(rule: dict[str, Any], normalized_command: str) -> re.Match[str] | None:
    if "command_regex" in rule:
        return re.fullmatch(str(rule["command_regex"]), normalized_command)
    expected = _normalize(rule.get("command", ""))
    return re.fullmatch(re.escape(expected), normalized_command) if expected == normalized_command else None


def _transform_capture(match: re.Match[str], transform: Any) -> Any:
    definition = transform if isinstance(transform, dict) else {"group": transform}
    raw = match.group(definition.get("group", 1))
    value_type = definition.get("type", "float")
    if value_type == "str":
        return str(raw)
    value: float | int = float(raw)
    value = value * float(definition.get("scale", 1.0)) + float(definition.get("offset", 0.0))
    if "round" in definition:
        value = round(value, int(definition["round"]))
    return int(round(value)) if value_type == "int" else value


def _get_state_path(state: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = state
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _set_state_path(state: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = state
    for part in parts[:-1]:
        current = current.setdefault(part, {})
        if not isinstance(current, dict):
            raise RuntimeError(f"Cannot set nested state path {path!r}")
    current[parts[-1]] = value


def _render_state_template(template: str, state: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        path = match.group(1)
        value = _get_state_path(state, path)
        if value is None:
            raise KeyError(path)
        if isinstance(value, list):
            return ",".join(str(item) for item in value)
        return str(value)

    return re.sub(r"\{([^{}]+)\}", replace, template)
