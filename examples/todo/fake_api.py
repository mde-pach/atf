"""A tiny in-memory todo API, so the example runs with no backend.

Real suites point at a real service; this stands in for one. Loopback only.
`python fake_api.py [port]` runs it standalone (for `atf serve` / `atf seed`).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

ACTOR_HEADER = "X-Actor"

COLLECTIONS = ("owners", "lists", "tasks", "labels", "guests")
ID_FIELDS = {"tasks": "uuid"}
PREFIX = {"owners": "own", "lists": "lst", "tasks": "tsk", "labels": "lbl", "guests": "gst"}


class TodoAPI:
    def __init__(self, actor: str = "example") -> None:
        self.actor = actor
        self.data: dict[str, list[dict[str, Any]]] = {name: [] for name in COLLECTIONS}
        self.counter = 0
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.reset()

    def reset(self) -> None:
        for name in COLLECTIONS:
            self.data[name] = []
        self.counter = 0
        # The environment ships with this label; the catalog references it, never creates it.
        self.data["labels"].append({"id": "lbl-seed", "slug": "urgent", "name": "Urgent"})

    # ---- lifecycle ----

    def start(self, port: int = 0) -> str:
        api = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                return

            def do_GET(self) -> None:
                api.handle(self, "GET")

            def do_POST(self) -> None:
                api.handle(self, "POST")

            def do_PATCH(self) -> None:
                api.handle(self, "PATCH")

            def do_DELETE(self) -> None:
                api.handle(self, "DELETE")

        self._server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        host, bound = self._server.server_address[0], self._server.server_address[1]
        return f"http://{host}:{bound}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    # ---- routing ----

    def handle(self, handler: BaseHTTPRequestHandler, method: str) -> None:
        parsed = urlparse(handler.path)
        parts = [part for part in parsed.path.split("/") if part]
        query = {key: values[0] for key, values in parse_qs(parsed.query).items()}

        if handler.headers.get(ACTOR_HEADER) != self.actor:
            return send(handler, 401, {"detail": f"{ACTOR_HEADER} header required"})

        # /owners/{id}/lists — the scoped listing `todo_list` uses
        if method == "GET" and len(parts) == 3 and parts[0] == "owners" and parts[2] == "lists":
            scoped = [item for item in self.data["lists"] if str(item.get("owner_id")) == parts[1]]
            return send(handler, 200, page(scoped, query))

        if len(parts) == 1 and parts[0] in COLLECTIONS:
            collection = parts[0]
            if method == "GET":
                return send(handler, 200, page(match(self.data[collection], query), query))
            if method == "POST":
                return send(handler, 201, self.create(collection, body(handler)))

        if len(parts) == 2 and parts[0] in COLLECTIONS:
            collection, identity = parts
            record = self.find(collection, identity)
            if record is None:
                return send(handler, 404, {"detail": "not found"})
            if method == "GET":
                # An activating guest becomes ready by the time it is next read, the way a real
                # asynchronous backend would settle. This is what the custom adapter polls for.
                if collection == "guests" and record.get("state") == "activating":
                    record["state"] = "ready"
                return send(handler, 200, record)
            if method == "PATCH":
                record.update(body(handler))
                return send(handler, 200, record)
            if method == "DELETE":
                self.data[collection].remove(record)
                return send(handler, 204, None)

        send(handler, 404, {"detail": "no route"})

    # ---- store ----

    def create(self, collection: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.counter += 1
        record = dict(payload)
        record[ID_FIELDS.get(collection, "id")] = f"{PREFIX[collection]}-{self.counter}"
        self.data[collection].append(record)
        return record

    def find(self, collection: str, identity: str) -> dict[str, Any] | None:
        key = ID_FIELDS.get(collection, "id")
        return next((item for item in self.data[collection] if str(item.get(key)) == identity), None)


def match(records: list[dict[str, Any]], query: dict[str, str]) -> list[dict[str, Any]]:
    filters = {key: value for key, value in query.items() if key not in {"limit", "offset"}}
    return [record for record in records if all(str(record.get(k)) == v for k, v in filters.items())]


def page(records: list[dict[str, Any]], query: dict[str, str]) -> dict[str, Any]:
    limit = int(query.get("limit", "100"))
    offset = int(query.get("offset", "0"))
    return {"results": records[offset : offset + limit], "count": len(records)}


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


if __name__ == "__main__":
    import os
    import sys

    api = TodoAPI(actor=os.environ.get("TODO_ACTOR", "example"))
    url = api.start(int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
    print(f"fake todo API on {url}\n  export TODO_URL={url} TODO_ACTOR={api.actor}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        api.stop()
