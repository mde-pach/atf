"""The environment the suites-under-test provision into. In-process, loopback, resettable."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

COLLECTIONS = ("owners", "lists", "guests")
ACTOR_HEADER = "X-Actor"


class StubBackend:
    def __init__(self, actor: str = "selftest") -> None:
        self.actor = actor
        self.data: dict[str, list[dict[str, Any]]] = {name: [] for name in COLLECTIONS}
        self.counter = 0
        self._server: ThreadingHTTPServer | None = None

    def reset(self) -> None:
        for name in COLLECTIONS:
            self.data[name] = []
        self.counter = 0

    def start(self, port: int = 0) -> str:
        backend = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                return

            def do_GET(self) -> None:
                backend.handle(self, "GET")

            def do_POST(self) -> None:
                backend.handle(self, "POST")

            def do_DELETE(self) -> None:
                backend.handle(self, "DELETE")

        self._server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        host, bound = self._server.server_address[0], self._server.server_address[1]
        return f"http://{host}:{bound}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    def handle(self, handler: BaseHTTPRequestHandler, method: str) -> None:
        parsed = urlparse(handler.path)
        parts = [part for part in parsed.path.split("/") if part]

        if method == "POST" and parts == ["_reset"]:
            self.reset()
            return send(handler, 200, {"ok": True})

        if handler.headers.get(ACTOR_HEADER) != self.actor:
            return send(handler, 401, {"detail": f"{ACTOR_HEADER} header required"})

        if len(parts) == 1 and parts[0] in COLLECTIONS:
            collection = parts[0]
            if method == "GET":
                query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
                filters = {k: v for k, v in query.items() if k not in {"limit", "offset"}}
                matched = [
                    record
                    for record in self.data[collection]
                    if all(str(record.get(k)) == v for k, v in filters.items())
                ]
                return send(handler, 200, {"results": matched, "count": len(matched)})
            if method == "POST":
                self.counter += 1
                record = {**body(handler), "id": f"{collection[:-1]}-{self.counter}"}
                self.data[collection].append(record)
                return send(handler, 201, record)

        if len(parts) == 2 and parts[0] in COLLECTIONS and method == "DELETE":
            bucket = self.data[parts[0]]
            self.data[parts[0]] = [record for record in bucket if str(record.get("id")) != parts[1]]
            return send(handler, 204, None)

        send(handler, 404, {"detail": "no route"})


def body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if not length:
        return {}
    try:
        payload = json.loads(handler.rfile.read(length))
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def send(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    raw = b"" if payload is None else json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    if raw:
        handler.wfile.write(raw)
