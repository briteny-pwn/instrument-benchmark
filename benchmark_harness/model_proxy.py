from __future__ import annotations

import http.client
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


ALLOWED_PATHS = {"/v1/messages", "/v1/messages/count_tokens"}
HOP_HEADERS = {"connection", "content-length", "host", "transfer-encoding"}


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802
        parsed_path = urlsplit(self.path)
        if parsed_path.path not in ALLOWED_PATHS:
            self.send_error(403, "endpoint not allowed")
            return
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length)
        upstream = urlsplit(os.environ.get("UPSTREAM_API_BASE", "https://api.anthropic.com"))
        connection_class = http.client.HTTPSConnection if upstream.scheme == "https" else http.client.HTTPConnection
        connection = connection_class(upstream.hostname, upstream.port, timeout=300)
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_HEADERS | {"authorization", "x-api-key"}
        }
        auth_header = os.environ.get("UPSTREAM_AUTH_HEADER", "x-api-key")
        auth_scheme = os.environ.get("UPSTREAM_AUTH_SCHEME", "")
        headers[auth_header] = f"{auth_scheme} {os.environ['UPSTREAM_API_KEY']}".strip()
        target = (upstream.path.rstrip("/") + parsed_path.path) or "/"
        if parsed_path.query:
            target += "?" + parsed_path.query
        connection.request("POST", target, body=body, headers=headers)
        response = connection.getresponse()
        self.send_response(response.status)
        for key, value in response.getheaders():
            if key.lower() not in HOP_HEADERS:
                self.send_header(key, value)
        self.send_header("connection", "close")
        self.end_headers()
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            self.wfile.write(chunk)
            self.wfile.flush()
        connection.close()

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    ThreadingHTTPServer(("0.0.0.0", 8080), ProxyHandler).serve_forever()


if __name__ == "__main__":
    main()
