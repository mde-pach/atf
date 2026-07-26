"""A tiny in-process REST API used to exercise the built-in adapters. Loopback only."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

SESSION_COOKIE = "stubsession"


class StubAPI:
    def __init__(
        self,
        require_header: tuple[str, str] | None = None,
        require_bearer: str | None = None,
        require_session: bool = False,
        paginate: bool = False,
        id_fields: dict[str, str] | None = None,
    ) -> None:
        self.records: dict[str, list[dict[str, Any]]] = {}
        self.require_header = require_header
        self.require_bearer = require_bearer
        self.require_session = require_session
        self.paginate = paginate
        self.id_fields = id_fields or {}
        self.requests: list[tuple[str, str]] = []
        self.next_id = 1
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ---- lifecycle ----

    def start(self) -> str:
        api = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # silence
                return

            def do_GET(self) -> None:
                api._handle(self, "GET")

            def do_POST(self) -> None:
                api._handle(self, "POST")

            def do_DELETE(self) -> None:
                api._handle(self, "DELETE")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        host, port = self._server.server_address[0], self._server.server_address[1]
        return f"http://{host}:{port}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def seed(self, collection: str, record: dict[str, Any]) -> dict[str, Any]:
        self.records.setdefault(collection, []).append(record)
        return record

    def paths(self, method: str) -> list[str]:
        return [path for verb, path in self.requests if verb == method]

    # ---- request handling ----

    def _handle(self, handler: BaseHTTPRequestHandler, method: str) -> None:
        parsed = urlparse(handler.path)
        self.requests.append((method, handler.path))
        parts = [part for part in parsed.path.split("/") if part]

        if method == "POST" and parsed.path == "/login":
            return self._login(handler)
        if not self._authorized(handler):
            return _send(handler, 401, {"detail": "unauthorized"})

        query = {key: values[0] for key, values in parse_qs(parsed.query).items()}

        if method == "GET" and len(parts) == 1:
            return self._list(handler, parts[0], query)
        if method == "GET" and len(parts) == 3:
            # scoped listing: /accounts/{id}/projects
            scoped = [
                record
                for record in self.records.get(parts[2], [])
                if str(record.get(f"{_singular(parts[0])}_id")) == parts[1]
            ]
            return self._respond_list(handler, scoped, query)
        if method == "POST" and len(parts) == 1:
            return self._create(handler, parts[0])
        if method == "DELETE" and len(parts) == 2:
            return self._delete(handler, parts[0], parts[1])
        _send(handler, 404, {"detail": "no route"})

    def _login(self, handler: BaseHTTPRequestHandler) -> None:
        payload = _body(handler)
        if payload.get("username") != "user" or payload.get("password") != "pass":
            return _send(handler, 403, {"detail": "bad credentials"})
        _send(
            handler,
            200,
            {"token": "session-token"},
            extra_headers=[("Set-Cookie", f"{SESSION_COOKIE}=ok; Path=/")],
        )

    def _authorized(self, handler: BaseHTTPRequestHandler) -> bool:
        if self.require_header is not None:
            name, value = self.require_header
            if handler.headers.get(name) != value:
                return False
        if self.require_bearer is not None and handler.headers.get("Authorization") != f"Bearer {self.require_bearer}":
            return False
        if self.require_session:
            cookie = handler.headers.get("Cookie") or ""
            if f"{SESSION_COOKIE}=ok" not in cookie:
                return False
        return True

    def _list(self, handler: BaseHTTPRequestHandler, collection: str, query: dict[str, str]) -> None:
        self._respond_list(handler, self.records.get(collection, []), query)

    def _respond_list(
        self,
        handler: BaseHTTPRequestHandler,
        records: list[dict[str, Any]],
        query: dict[str, str],
    ) -> None:
        filters = {key: value for key, value in query.items() if key not in {"limit", "offset"}}
        matched = [
            record for record in records if all(str(record.get(key)) == value for key, value in filters.items())
        ]
        if not self.paginate:
            return _send(handler, 200, matched)
        limit = int(query.get("limit", "100"))
        offset = int(query.get("offset", "0"))
        _send(handler, 200, {"results": matched[offset : offset + limit], "count": len(matched)})

    def _create(self, handler: BaseHTTPRequestHandler, collection: str) -> None:
        record = dict(_body(handler))
        id_field = self.id_fields.get(collection, "id")
        record[id_field] = f"{_singular(collection)}-{self.next_id}"
        self.next_id += 1
        self.records.setdefault(collection, []).append(record)
        _send(handler, 201, record)

    def _delete(self, handler: BaseHTTPRequestHandler, collection: str, identity: str) -> None:
        id_field = self.id_fields.get(collection, "id")
        bucket = self.records.get(collection, [])
        remaining = [record for record in bucket if str(record.get(id_field)) != identity]
        if len(remaining) == len(bucket):
            return _send(handler, 404, {"detail": "gone"})
        self.records[collection] = remaining
        _send(handler, 204, None)


def _singular(collection: str) -> str:
    return collection[:-1] if collection.endswith("s") else collection


def _body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if not length:
        return {}
    raw = handler.rfile.read(length)
    content_type = handler.headers.get("Content-Type") or ""
    if content_type.startswith("application/x-www-form-urlencoded"):
        return {key: values[0] for key, values in parse_qs(raw.decode()).items()}
    try:
        payload = json.loads(raw)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _send(
    handler: BaseHTTPRequestHandler,
    status: int,
    payload: Any,
    extra_headers: list[tuple[str, str]] | None = None,
) -> None:
    body = b"" if payload is None else json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    for name, value in extra_headers or []:
        handler.send_header(name, value)
    handler.end_headers()
    if body:
        handler.wfile.write(body)
