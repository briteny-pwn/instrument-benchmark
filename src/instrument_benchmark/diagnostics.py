"""Sanitization shared by terminal diagnostics and persisted process logs."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping


class Redactor:
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self.secrets: set[str] = {value for value in secrets if value}

    def add_environment(self, environment: Mapping[str, str | None]) -> None:
        for name, value in environment.items():
            if value and any(
                part in name.upper()
                for part in ("TOKEN", "API_KEY", "PASSWORD", "SECRET")
            ):
                self.secrets.add(value)

    def __call__(self, value: str) -> str:
        for secret in sorted(self.secrets, key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", value)
        value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
        value = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", value)
        value = re.sub(r"(?i)(https?://)[^/\s@]+@", r"\1[REDACTED]@", value)
        value = re.sub(
            r"(?i)(authorization\\?[\"']?\s*[:=]\s*\\?[\"'])(?:bearer\s+|basic\s+)?[^\\\"']*(\\?[\"'])",
            r"\1[REDACTED]\2",
            value,
        )
        value = re.sub(
            r"(?i)(authorization\\?[\"']?\s*[:=]\s*)(?:bearer\s+|basic\s+)?[^\s,\\\"']+",
            r"\1[REDACTED]",
            value,
        )
        value = re.sub(
            r"(?i)((?:api[_-]?key|access[_-]?token|auth[_-]?token|password|secret)[\"']?\s*[:=]\s*[\"']?)[^\s&\"',}]+",
            r"\1[REDACTED]",
            value,
        )
        return value

    def line(self, value: str) -> str:
        return self(value).replace("\n", r"\n").replace("\t", r"\t")

    def value(self, value: object) -> object:
        if isinstance(value, str):
            return self(value)
        if isinstance(value, dict):
            return {str(key): self.value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.value(item) for item in value]
        return value
