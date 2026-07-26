"""The provisioning engine (§8). Domain-free: it dispatches to adapters and never branches per system."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from .adapters import Adapter, Record, close_adapter, registered_systems
from .catalog import Node, find_node, load_catalog
from .placeholders import Unresolved
from .placeholders import resolve as resolve_placeholders

log = logging.getLogger("atf.materializer")

PRESENT = "present"
ABSENT = "absent"
EPHEMERAL = "ephemeral"
UNSUPPORTED = "unsupported"
ERROR = "error"
BLOCKED = "blocked"


class ProvisioningError(Exception):
    def __init__(self, node_id: str, detail: str) -> None:
        self.node_id = node_id
        self.detail = detail
        super().__init__(f"could not provision {node_id}: {detail}")


class UnknownResource(LookupError):
    pass


class Materializer:
    def __init__(self, catalog_root: Path | str, env: str, adapters: dict[str, Adapter]) -> None:
        self.catalog_root = Path(catalog_root)
        self.env = env
        self.adapters = adapters
        self.types: dict[str, dict[str, Any]] = {}
        self.nodes: dict[str, Node] = {}
        self._ids: dict[str, Any] = {}
        self._cache: dict[str, Any] = {}
        self.reload()

    # ---- catalog ----------------------------------------------------------

    def reload(self) -> None:
        self.types, self.nodes = load_catalog(self.catalog_root, registered_systems())
        self._ids.clear()
        self._cache.clear()

    def resource_types(self) -> list[str]:
        return sorted(self.types)

    def resolve_id(self, resource_type: str, name: str) -> str:
        node = find_node(self.nodes, resource_type, name)
        if node is None:
            raise UnknownResource(f"no {resource_type} named {name!r} in the catalog")
        return node["id"]

    def node(self, nid: str) -> Node:
        try:
            return self.nodes[nid]
        except KeyError:
            raise UnknownResource(f"unknown resource {nid!r}") from None

    # ---- adapter-facing context (§7.1) ------------------------------------

    def resolve(self, value: Any) -> Any:
        return resolve_placeholders(value, self.identity_of)

    def cached(self, key: str, loader: Callable[[], Any]) -> Any:
        if key not in self._cache:
            self._cache[key] = loader()
        return self._cache[key]

    def invalidate_cache(self) -> None:
        self._cache.clear()

    def identity_of(self, nid: str) -> Any:
        """Identity of a node: known from this pass, else looked up live. `None` when absent."""
        if nid in self._ids:
            return self._ids[nid]
        node = self.nodes.get(nid)
        if node is None:
            return None
        record = self.find_existing(node)
        identity = None if record is None else record.get(node["id_field"])
        self._ids[nid] = identity
        return identity

    # ---- graph ------------------------------------------------------------

    def closure(self, nid: str) -> list[str]:
        """`nid` plus every transitive dependency."""
        seen: list[str] = []
        stack = [nid]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            node = self.node(current)
            seen.append(current)
            stack.extend(node["depends_on"])
        return seen

    def topo(self, subset: Iterable[str]) -> list[str]:
        """Dependency-first order within `subset`."""
        wanted = list(dict.fromkeys(subset))
        members = set(wanted)
        ordered: list[str] = []
        placed: set[str] = set()

        def visit(nid: str, seen: frozenset[str]) -> None:
            if nid in placed or nid in seen:
                return
            for dep in self.node(nid)["depends_on"]:
                if dep in members:
                    visit(dep, seen | {nid})
            if nid not in placed:
                placed.add(nid)
                ordered.append(nid)

        for nid in wanted:
            visit(nid, frozenset())
        return ordered

    # ---- reads ------------------------------------------------------------

    def find_existing(self, node: Node) -> Record | None:
        if node["lifecycle"] == EPHEMERAL:
            return None
        adapter = self.adapters.get(node["system"])
        if adapter is None:
            return None
        try:
            return adapter.find(node, self)
        except Unresolved:
            return None

    def status(self, collection: str | None = None) -> dict[str, dict[str, Any]]:
        self._ids.clear()
        self.invalidate_cache()
        out: dict[str, dict[str, Any]] = {}
        for nid, node in sorted(self.nodes.items()):
            if collection is not None and node["collection"] != collection:
                continue
            out[nid] = self._status_of(node)
        return out

    def _status_of(self, node: Node) -> dict[str, Any]:
        if node["system"] not in self.adapters:
            return {"status": UNSUPPORTED, "detail": f"no adapter for system {node['system']!r} in env {self.env}"}
        if node["lifecycle"] == EPHEMERAL:
            return {"status": EPHEMERAL, "detail": "built per run"}
        try:
            record = self.find_existing(node)
        except Exception as exc:
            return {"status": ERROR, "detail": _short(exc)}
        if record is None:
            return {"status": ABSENT, "detail": ""}
        identity = record.get(node["id_field"])
        self._ids[node["id"]] = identity
        return {"status": PRESENT, "detail": "", "identity": identity}

    # ---- writes -----------------------------------------------------------

    def materialize(self, subset: Iterable[str], keep_going: bool = False) -> dict[str, Any]:
        """Provision `subset` and everything it depends on, dependency-first.

        Stops at the first failure by default: provisioning failures are usually correlated (a bad
        token, an unreachable backend), so continuing turns one clear error into many identical
        ones. With `keep_going`, a failed node's dependents are reported `blocked` and independent
        subtrees are still attempted — useful when seeding a whole catalog.
        """
        # A listing is memoised for the duration of one pass, not the session: the materializer is
        # session-scoped, and the system under test mutates the same backend between passes.
        self._ids.clear()
        self.invalidate_cache()
        results: list[dict[str, Any]] = []
        records: dict[str, Record] = {}

        # Provision the closure of what was asked for, not just the listed nodes: a dependency
        # excluded from `subset` (an ephemeral one, say) would otherwise be unresolvable.
        wanted: list[str] = []
        for nid in dict.fromkeys(subset):
            wanted.extend(item for item in self.closure(nid) if item not in wanted)

        stalled: set[str] = set()

        for nid in self.topo(wanted):
            node = self.node(nid)

            # Dependencies come first in topo order, so checking the direct ones is transitive.
            blocker = next((dep for dep in node["depends_on"] if dep in stalled), None)
            if blocker is not None:
                results.append(
                    {
                        "id": nid,
                        "action": BLOCKED,
                        "ok": False,
                        "detail": f"depends on {blocker}, which did not provision",
                    }
                )
                stalled.add(nid)
                continue

            outcome = self._attempt(node)
            results.append(outcome)
            if outcome["ok"]:
                record = outcome.pop("record")
                self._ids[nid] = record.get(node["id_field"])
                records[nid] = record
                continue

            stalled.add(nid)
            if not keep_going:
                break

        return {"results": results, "records": records}

    def _attempt(self, node: Node) -> dict[str, Any]:
        """Provision one node. Returns a result entry, carrying `record` when it succeeded."""
        nid = node["id"]
        adapter = self.adapters.get(node["system"])
        if adapter is None:
            detail = f"no adapter for system {node['system']!r} in env {self.env}"
            return {"id": nid, "action": UNSUPPORTED, "ok": False, "detail": detail}

        try:
            record, action = self._provision(node, adapter)
        except Exception as exc:  # noqa: BLE001 - reported, not raised: callers read `results`
            return {"id": nid, "action": ERROR, "ok": False, "detail": _short(exc)}

        if record is None:
            return {"id": nid, "action": action, "ok": False, "detail": "reference resource not found"}
        return {"id": nid, "action": action, "ok": True, "record": record}

    def _provision(self, node: Node, adapter: Adapter) -> tuple[Record | None, str]:
        if node["mode"] == "reference":
            return adapter.find(node, self), "reference"

        existing = None if node["lifecycle"] == EPHEMERAL else adapter.find(node, self)
        if existing is not None:
            return existing, "exists"

        body = self.resolve(node["body"])
        record = adapter.create(node, body, self)
        self.invalidate_cache()
        return record, "created"

    def create_closure(self, nid: str, keep_going: bool = False) -> dict[str, Any]:
        return self.materialize(self.closure(nid), keep_going=keep_going)

    def create_all(self, keep_going: bool = False) -> dict[str, Any]:
        return self.materialize(list(self.nodes), keep_going=keep_going)

    def ensure(self, resource_type: str, name: str) -> Record:
        return self.ensure_closure(resource_type, name)[0]

    def ensure_closure(self, resource_type: str, name: str) -> tuple[Record, dict[str, Record]]:
        """The target's record, plus every record provisioned to get there.

        Callers need the second element to tear down ephemeral resources reached *through* a
        dependency — those are created on every pass and nothing else would ever delete them.
        """
        nid = self.resolve_id(resource_type, name)
        outcome = self.create_closure(nid)
        for result in outcome["results"]:
            if not result["ok"]:
                raise ProvisioningError(str(result["id"]), str(result.get("detail", "")))
        records: dict[str, Record] = outcome["records"]
        record = records.get(nid)
        if record is None:
            raise ProvisioningError(nid, "adapter returned no record")
        return record, records

    def ephemeral_records(self, records: Mapping[str, Record]) -> list[tuple[str, Record]]:
        return [
            (nid, record)
            for nid, record in records.items()
            if nid in self.nodes and self.nodes[nid]["lifecycle"] == EPHEMERAL
        ]

    def close(self) -> None:
        """Release every adapter's resources. Safe to call more than once."""
        for adapter in self.adapters.values():
            close_adapter(adapter)

    def teardown(self, records: Mapping[str, Record] | Iterable[tuple[str, Record]]) -> None:
        """Best-effort delete of ephemeral resources. Never raises.

        Accepts pairs as well as a mapping, because one scenario can provision several instances
        of the same ephemeral node — each is a distinct record that has to be deleted.
        """
        source: Any = records.items() if isinstance(records, Mapping) else records
        pairs: list[tuple[str, Record]] = [(str(nid), record) for nid, record in source]
        for nid, record in pairs:
            node = self.nodes.get(nid)
            if node is None or node["lifecycle"] != EPHEMERAL:
                continue
            adapter = self.adapters.get(node["system"])
            if adapter is None:
                continue
            try:
                adapter.delete(node, record, self)
            except Exception as exc:
                log.warning("teardown of %s failed: %s", nid, _short(exc))


def _short(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    first = text.splitlines()[0]
    return first if len(first) <= 200 else first[:197] + "..."
