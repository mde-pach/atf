"""An in-memory adapter used by the framework's own tests. No network anywhere."""

from __future__ import annotations

from typing import Any

from atf.adapters import Context, Record, register
from atf.catalog import Node


class FakeAdapter:
    """Stores records per resource type, keyed by the type's natural key."""

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self.settings = settings or {}
        self.store: dict[str, list[Record]] = {}
        self.calls: list[tuple[str, str]] = []
        self.fail_create: set[str] = set()
        self.next_id = 1

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> FakeAdapter:
        return cls(settings)

    # ---- SPI ----

    def find(self, node: Node, ctx: Context) -> Record | None:
        self.calls.append(("find", node["id"]))
        criteria = self._criteria(node, ctx)
        if criteria is None:
            return None
        for record in self.store.get(node["resource"], []):
            if all(record.get(key) == value for key, value in criteria.items()):
                return record
        return None

    def create(self, node: Node, body: Record, ctx: Context) -> Record:
        self.calls.append(("create", node["id"]))
        if node["id"] in self.fail_create:
            raise ValueError(f"backend refused to create {node['id']}")
        record = dict(body)
        record[node["id_field"]] = f"{node['resource']}-{self.next_id}"
        self.next_id += 1
        self.store.setdefault(node["resource"], []).append(record)
        return record

    def delete(self, node: Node, record: Record, ctx: Context) -> None:
        self.calls.append(("delete", node["id"]))
        bucket = self.store.get(node["resource"], [])
        self.store[node["resource"]] = [item for item in bucket if item is not record]

    # ---- helpers ----

    def _criteria(self, node: Node, ctx: Context) -> dict[str, Any] | None:
        from atf.placeholders import Unresolved

        keys = node["config"].get("natural_key")
        if isinstance(keys, str):
            keys = [keys]
        if not keys:
            return None
        criteria: dict[str, Any] = {}
        for key in keys:
            if key not in node["body"]:
                return None
            try:
                criteria[str(key)] = ctx.resolve(node["body"][key])
            except Unresolved:
                return None
        return criteria

    def seed(self, resource: str, record: Record) -> Record:
        self.store.setdefault(resource, []).append(record)
        return record

    def actions(self, kind: str) -> list[str]:
        return [nid for action, nid in self.calls if action == kind]


def register_fake(system: str = "fake") -> FakeAdapter:
    adapter = FakeAdapter()
    register(system, lambda settings: adapter)
    return adapter
