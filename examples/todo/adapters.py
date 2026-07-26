"""The escape hatch: a custom adapter whose `create` runs a multi-step chain.

A guest is signed up, then activated, then polled until the backend reports it ready — three
calls the declarative REST adapter cannot express. Modelled as one adapter, so the catalog
treats a guest like any other resource.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

from atf import http
from atf.adapters import Context, Record, register
from atf.catalog import Node

READY_TIMEOUT = 5.0

# ATF imports this module (it is listed under `adapters:` in the manifest) before it resolves the
# manifest's `*_env` pointers, so this is the one place that can stand a backend up for *every*
# entry point — `atf serve`, `atf status`, `atf seed` and the cockpit alike. A real suite points
# TODO_URL at a real service and none of this runs.
if not os.environ.get("TODO_URL"):
    sys.path.insert(0, str(Path(__file__).parent))
    from fake_api import TodoAPI

    os.environ.setdefault("TODO_ACTOR", "example")
    _api = TodoAPI(actor=os.environ["TODO_ACTOR"])
    os.environ["TODO_URL"] = _api.start()
    print(f"examples/todo: no TODO_URL set, started the stand-in API on {os.environ['TODO_URL']}")


class GuestAdapter:
    def __init__(self, settings: dict[str, Any]) -> None:
        self.client = http.build_client(
            settings["base_url"],
            auth=settings.get("auth"),
            timeout=float(settings.get("timeout", 10)),
        )

    def find(self, node: Node, ctx: Context) -> Record | None:
        return None  # ephemeral: never reused across runs

    def create(self, node: Node, body: Record, ctx: Context) -> Record:
        identity_field = node["id_field"]

        signup = self.client.post("/guests", json={**body, "state": "pending"})
        signup.raise_for_status()
        identity = signup.json()[identity_field]

        # The backend flips `activating` to `ready` on its own; we poll until it has.
        activate = self.client.patch(f"/guests/{identity}", json={"state": "activating"})
        activate.raise_for_status()

        return self._await_ready(identity, node["id"])

    def delete(self, node: Node, record: Record, ctx: Context) -> None:
        self.client.delete(f"/guests/{record[node['id_field']]}")

    def _await_ready(self, identity: str, node_id: str) -> Record:
        deadline = time.time() + READY_TIMEOUT
        while True:
            response = self.client.get(f"/guests/{identity}")
            response.raise_for_status()
            record = response.json()
            if record.get("state") == "ready":
                return record
            if time.time() > deadline:
                raise TimeoutError(f"{node_id}: guest {identity} never became ready")
            time.sleep(0.05)


register("guest", GuestAdapter)
