"""The provisioning engine.

Walks a resource's dependency closure, orders it dependency-first, and asks the adapter for each
node in turn: does this exist, and if not, create it. Domain-free — it dispatches to adapters and
never branches per system.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, TypeVar, cast

from .adapters import Adapter, Browsable, Record, can_browse, close_adapter, registered_systems
from .catalog import DATA, UNIVERSAL_TYPE_KEYS, Node, find_node, load_catalog
from .catalog import REFERENCE as REFERENCE_MODE
from .placeholders import Unresolved
from .placeholders import resolve as resolve_placeholders

log = logging.getLogger("atf.materializer")

PRESENT = "present"
ABSENT = "absent"
EPHEMERAL = "ephemeral"
UNSUPPORTED = "unsupported"
ERROR = "error"
BLOCKED = "blocked"

CREATED = "created"
EXISTS = "exists"
REFERENCE = "reference"
OBSERVED = "observed"

_T = TypeVar("_T")


class ProvisioningError(Exception):
    def __init__(self, node_id: str, detail: str) -> None:
        self.node_id = node_id
        self.detail = detail
        super().__init__(f"could not provision {node_id}: {detail}")


class UnknownResource(LookupError):
    pass


class ScopeRequired(Exception):
    """Browsing this type needs a parent named first, because its listing is scoped to one."""

    def __init__(self, resource_type: str, fields: list[str]) -> None:
        self.resource_type = resource_type
        self.fields = fields
        super().__init__(f"listing {resource_type!r} needs {', '.join(fields)} to scope it")


class Materializer:
    def __init__(self, catalog_root: Path | str, env: str, adapters: dict[str, Adapter]) -> None:
        self.catalog_root = Path(catalog_root)
        self.env = env
        self.adapters = adapters
        self.types: dict[str, dict[str, Any]] = {}
        self.nodes: dict[str, Node] = {}
        self._ids: dict[str, Any] = {}
        self._cache: dict[str, Any] = {}
        # Generated values, held for one scenario. A `${fake:email}` written in a body and again in
        # the assertion checking it has to be the same email, or the assertion can never pass.
        self._generated: dict[str, Any] = {}
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

    # ---- adapter-facing context ---------------------------------------------
    # The materializer passes itself to adapters as `ctx`; these are the methods an adapter may
    # call on it.

    def resolve(self, value: Any) -> Any:
        return resolve_placeholders(value, self.identity_of, self._generated)

    def forget_scenario(self) -> None:
        """Start a fresh scenario: nothing the last one learned is this one's to assume.

        Two things are dropped. **Generated values**, because within a scenario they must stand
        still — a `${fake:email}` written in a body and again in the assertion checking it has to be
        the same email — and across scenarios they must not, or an ephemeral resource meant to be
        new every time is not. **Known identities**, because a resource that was absent when the
        last scenario looked may exist now, and one that existed may be gone; `_ids` caches `None`
        as readily as an id, and a stale `None` makes `${owners.primary.id}` unresolvable for the
        rest of the session.

        Called once per scenario by the plugin. A provisioning pass clears `_ids` too, so this only
        adds the case of a scenario that asserts without provisioning first.
        """
        self._generated.clear()
        self._ids.clear()

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

    def browse_fields(self, resource_type: str) -> list[str]:
        """Fields a scoped listing needs before it can run — empty when the type lists globally.

        A type whose `list_path` is scoped to a parent (`/owners/{owner_id}/lists`) cannot be
        enumerated without knowing which parent, so the caller has to supply one.
        """
        import string

        entry = self.types.get(resource_type) or {}
        template = entry.get("list_path")
        if not isinstance(template, str) or not template:
            return []
        return [name for _, name, _, _ in string.Formatter().parse(template) if name]

    def browse(self, resource_type: str, limit: int = 200, scope: dict[str, Any] | None = None) -> list[Record]:
        """Every record this type already has in the environment.

        Answers the question a catalog author actually starts with — "what is out there?" — so a
        node can be written from a real record instead of guessed. Adapters opt in by implementing
        `browse`; one that does not simply has nothing to show.
        """
        entry = self.types.get(resource_type)
        if entry is None:
            raise KeyError(f"no resource type {resource_type!r} in the catalog")
        adapter = self.adapters.get(str(entry.get("system", "")))
        if adapter is None or not can_browse(adapter):
            return []

        needed = [field for field in self.browse_fields(resource_type) if field not in (scope or {})]
        if needed:
            raise ScopeRequired(resource_type, needed)
        return cast("Browsable", adapter).browse(self.probe(resource_type, scope), self, limit)

    def probe(self, resource_type: str, scope: dict[str, Any] | None = None) -> Node:
        """A node that exists only to carry a type's config to an adapter, with no instance behind it."""
        entry = self.types.get(resource_type) or {}
        config = {key: value for key, value in entry.items() if key not in UNIVERSAL_TYPE_KEYS}
        return Node(
            id=f"{resource_type}.*",
            collection="",
            name="*",
            resource=resource_type,
            system=str(entry.get("system", "")),
            mode=str(entry.get("mode", "create")),
            lifecycle=str(entry.get("lifecycle", "persistent")),
            id_field=str(entry.get("id_field", "id")),
            config=config,
            represents="",
            depends_on=[],
            dependents=[],
            body=dict(scope or {}),
        )

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
        # The record travels with the status because a caller offering an assertion on one of its
        # fields needs to know which fields there are, and what each holds right now. Reading it a
        # second time would ask the backend the same question twice per page.
        return {"status": PRESENT, "detail": "", "identity": identity, "record": record}

    # ---- writes -----------------------------------------------------------

    def provisionable(self, node_id: str) -> tuple[bool, str]:
        """Whether provisioning this node can create it, and why not when it cannot.

        Callers offering a "create it" action ask first: attempting either of these can only
        report the same refusal back, so the honest UI never offers the button.
        """
        node = self.node(node_id)
        if node["mode"] == REFERENCE_MODE:
            return False, "reference resources must already exist in the environment — ATF never creates them"
        if node["mode"] == DATA:
            return False, "an observation, not a resource ATF makes — there is nothing here to create"
        if node["lifecycle"] == EPHEMERAL:
            return False, "built fresh for every run by the test that needs it"
        return True, ""

    def materialize(
        self,
        subset: Iterable[str],
        keep_going: bool = False,
        on_start: Callable[[str], None] | None = None,
        on_result: Callable[[dict[str, Any]], None] | None = None,
        overrides: Mapping[str, Record] | None = None,
    ) -> dict[str, Any]:
        """Provision `subset` and everything it depends on, dependency-first.

        Stops at the first failure by default: provisioning failures are usually correlated (a bad
        token, an unreachable backend), so continuing turns one clear error into many identical
        ones. With `keep_going`, a failed node's dependents are reported `blocked` and independent
        subtrees are still attempted — useful when seeding a whole catalog.

        `on_start` and `on_result` observe the pass as it happens, node by node, for a caller
        showing progress; they see exactly the entries the return value collects.
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
                blocked = {
                    "id": nid,
                    "action": BLOCKED,
                    "ok": False,
                    "detail": f"depends on {blocker}, which did not provision",
                }
                results.append(blocked)
                stalled.add(nid)
                _notify(on_result, blocked)
                continue

            _notify(on_start, nid)
            outcome = self._attempt(node, (overrides or {}).get(nid))
            results.append(outcome)
            if outcome["ok"]:
                record = outcome.pop("record")
                self._ids[nid] = record.get(node["id_field"])
                records[nid] = record
                _notify(on_result, outcome)
                continue

            stalled.add(nid)
            _notify(on_result, outcome)
            if not keep_going:
                break

        return {"results": results, "records": records}

    def _attempt(self, node: Node, overrides: Record | None = None) -> dict[str, Any]:
        """Provision one node. Returns a result entry, carrying `record` when it succeeded."""
        nid = node["id"]
        adapter = self.adapters.get(node["system"])
        if adapter is None:
            detail = f"no adapter for system {node['system']!r} in env {self.env}"
            return {"id": nid, "action": UNSUPPORTED, "ok": False, "detail": detail}

        try:
            record, action = self._provision(_varied(node, overrides), adapter)
        except Exception as exc:  # noqa: BLE001 - reported, not raised: callers read `results`
            return {"id": nid, "action": ERROR, "ok": False, "detail": _short(exc)}

        if record is None:
            # An absent observation is an answer, not a failure: `data` says "look at this", and
            # "it is not there" is one of the things a scenario may want to claim about it.
            if node["mode"] == DATA:
                return {"id": nid, "action": OBSERVED, "ok": True, "record": {}}
            return {"id": nid, "action": action, "ok": False, "detail": "reference resource not found"}
        return {"id": nid, "action": action, "ok": True, "record": record}

    def _provision(self, node: Node, adapter: Adapter) -> tuple[Record | None, str]:
        if node["mode"] == DATA:
            return adapter.find(node, self), OBSERVED
        if node["mode"] == REFERENCE_MODE:
            return adapter.find(node, self), REFERENCE

        existing = None if node["lifecycle"] == EPHEMERAL else adapter.find(node, self)
        if existing is not None:
            return existing, EXISTS

        body = self.resolve(node["body"])
        record = adapter.create(node, body, self)
        self.invalidate_cache()
        return record, CREATED

    def create_closure(
        self, nid: str, keep_going: bool = False, overrides: Mapping[str, Record] | None = None
    ) -> dict[str, Any]:
        return self.materialize(self.closure(nid), keep_going=keep_going, overrides=overrides)

    def create_all(self, keep_going: bool = False) -> dict[str, Any]:
        return self.materialize(list(self.nodes), keep_going=keep_going)

    def ensure(self, resource_type: str, name: str, overrides: Record | None = None) -> Record:
        return self.ensure_closure(resource_type, name, overrides)[0]

    def ensure_closure(
        self, resource_type: str, name: str, overrides: Record | None = None
    ) -> tuple[Record, dict[str, Record]]:
        """The target's record, plus every record provisioned to get there.

        Callers need the second element to tear down ephemeral resources reached *through* a
        dependency — those are created on every pass and nothing else would ever delete them.

        `overrides` vary *this* node's body for this pass only, which is what lets a scenario say
        `Given the task "milk" but: | due_at | ... |` instead of the catalog needing a second node
        for every variation anyone ever wants. The catalog is untouched — see `_varied`.
        """
        nid = self.resolve_id(resource_type, name)
        outcome = self.create_closure(nid, overrides={nid: overrides} if overrides else None)
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


def _varied(node: Node, overrides: Record | None) -> Node:
    """This node with some of its body written differently, for one pass.

    A copy, never the node itself: `self.nodes` is session state that every other scenario reads,
    and a variation that outlived the scenario asking for it would be a shared fixture wearing a
    different hat — which is the problem inline variation exists to solve.

    The varied body is what `find` matches on as well as what `create` sends, so overriding a field
    of the natural key genuinely selects a different resource, and overriding anything else changes
    what a newly created one holds.
    """
    if not overrides:
        return node
    varied = dict(node)
    varied["body"] = {**node["body"], **overrides}
    return cast("Node", varied)


def _notify(callback: Callable[[_T], None] | None, value: _T) -> None:
    if callback is not None:
        callback(value)


def _short(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    first = text.splitlines()[0]
    return first if len(first) <= 200 else first[:197] + "..."
