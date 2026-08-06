"""A small REST API over the same domain, so `@rest` can be read beside `@sqlite`.

Not part of ATF. It is the product under test, and it is deliberately awkward in one way: an owner
is *unique* by email and *fetchable* only by a numeric id. That is the split `find` exists for.
"""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import unquote

OWNERS: dict[int, dict] = {}
LISTS: dict[int, dict] = {}
NEXT = {"owners": 1, "lists": 1}
TABLES = {"owners": OWNERS, "lists": LISTS}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, payload=None):
        body = json.dumps(payload).encode() if payload is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _route(self):
        path, _, query = self.path.partition("?")
        parts = [p for p in path.split("/") if p]
        params = {k: unquote(v) for k, v in (p.split("=", 1) for p in query.split("&") if "=" in p)}
        return parts, params

    def _read(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        parts, params = self._route()
        if not parts or parts[0] not in TABLES:
            return self._send(404)
        table = TABLES[parts[0]]
        if len(parts) == 2:
            found = table.get(int(parts[1])) if parts[1].isdigit() else None
            return self._send(200, found) if found else self._send(404)
        rows = list(table.values())
        for key, value in params.items():
            rows = [row for row in rows if str(row.get(key)) == value]
        return self._send(200, {"items": rows})

    def do_POST(self):
        parts, _ = self._route()
        if not parts or parts[0] not in TABLES:
            return self._send(404)
        table, name = TABLES[parts[0]], parts[0]
        row = {"id": NEXT[name], **self._read()}
        NEXT[name] += 1
        table[row["id"]] = row
        return self._send(201, row)

    def do_PATCH(self):
        parts, _ = self._route()
        if len(parts) != 2 or parts[0] not in TABLES:
            return self._send(404)
        row = TABLES[parts[0]].get(int(parts[1]))
        if row is None:
            return self._send(404)
        row.update(self._read())
        return self._send(200, row)

    def do_DELETE(self):
        parts, _ = self._route()
        if len(parts) != 2 or parts[0] not in TABLES:
            return self._send(404)
        TABLES[parts[0]].pop(int(parts[1]), None)
        return self._send(204)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8799), Handler).serve_forever()
