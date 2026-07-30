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

from ..adapters import (
    Actionable,
    Adapter,
    Browsable,
    Record,
    can_act,
    can_browse,
    close_adapter,
    registered_systems,
)
from ..model.catalog import Catalog, Node, load_catalog
from ..model.placeholders import Unresolved, references
from ..model.placeholders import resolve as resolve_placeholders
from ..model.typespec import BUILT_IN_ACTIONS, DATA, EPHEMERAL, REFERENCE, TypeSpec
from .status import (
    ABSENT,
    BLOCKED,
    CREATED,
    ERROR,
    EXISTS,
    OBSERVED,
    PRESENT,
    UNSUPPORTED,
    ProvisionOutcome,
    ProvisionResult,
    ResourceStatus,
    Statuses,
)

log = logging.getLogger("atf.materializer")

# ---- an instance of one scenario's own --------------------------------------
#
# A normally-persistent resource is shared: found once, left in place, and every scenario that names
# it gets the same one. `Given a fresh <type> "<name>"` asks for an instance of that same catalog
# node that belongs to one scenario and is taken away with it — the case §4.7 of the target calls
# the point of per-node lifecycle, since without it a suite has to choose *per type* between cheap
# and isolated.
#
# What makes one instance not the other is its natural key, which is the one thing ATF already
# understands about identity. So a fresh instance is the node with a discriminator appended to each
# key field that is text of its own, and nothing else about it changes.

# What separates the discriminator from the value the catalog wrote. Visible in the data on purpose:
# an instance a killed run left behind then says what it was, rather than looking like a typo.
FRESH_MARK = "-fresh-"

# How much of a `${uuid}` is enough to tell two of them apart. Eight hex characters is four billion,
# and appending the full thirty-two would push slugs and names past the length limits real backends
# have — which would be ATF breaking a suite in the name of isolating it.
FRESH_TAG = 8

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
        self.catalog = Catalog()
        self._ids: dict[str, Any] = {}
        self._cache: dict[str, Any] = {}
        # Generated values, held for one scenario. A `${fake:email}` written in a body and again in
        # the assertion checking it has to be the same email, or the assertion can never pass.
        self._generated: dict[str, Any] = {}
        # The instances this scenario asked to have to itself: the node as it was varied to make one
        # (the key it was given, still written as `${...}`), and the record that came back. Held for
        # one scenario, because that is exactly how long such an instance lives.
        self._fresh: dict[str, tuple[Node, Record]] = {}
        self._isolated = 0
        self.reload()

    # ---- catalog ----------------------------------------------------------

    def reload(self) -> None:
        self.catalog = load_catalog(self.catalog_root, registered_systems())
        self._ids.clear()
        self._cache.clear()

    @property
    def types(self) -> dict[str, TypeSpec]:
        return self.catalog.types

    @property
    def nodes(self) -> dict[str, Node]:
        return self.catalog.nodes

    def resource_types(self) -> list[str]:
        return self.catalog.resource_types

    def spec(self, resource_type: str) -> TypeSpec:
        spec = self.catalog.spec(resource_type)
        if spec is None:
            raise UnknownResource(f"no resource type {resource_type!r} in the catalog")
        return spec

    def resolve_id(self, resource_type: str, name: str) -> str:
        node = self.catalog.find(resource_type, name)
        if node is None:
            raise UnknownResource(f"no {resource_type} named {name!r} in the catalog")
        return node.id

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

        The instances a scenario had to itself go with them: one is torn down when its scenario
        ends, so remembering it into the next one could only ever point at something deleted.
        """
        self._generated.clear()
        self._ids.clear()
        self._fresh.clear()
        self._isolated = 0

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
        identity = None if record is None else record.get(node.id_field)
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
            stack.extend(node.depends_on)
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
            for dep in self.node(nid).depends_on:
                if dep in members:
                    visit(dep, seen | {nid})
            if nid not in placed:
                placed.add(nid)
                ordered.append(nid)

        for nid in wanted:
            visit(nid, frozenset())
        return ordered

    # ---- reads ------------------------------------------------------------

    def browse(self, resource_type: str, limit: int = 200, scope: dict[str, Any] | None = None) -> list[Record]:
        """Every record this type already has in the environment.

        Answers the question a catalog author actually starts with — "what is out there?" — so a
        node can be written from a real record instead of guessed. Adapters opt in by implementing
        `browse`; one that does not simply has nothing to show.
        """
        spec = self.spec(resource_type)
        adapter = self.adapters.get(spec.system)
        if adapter is None or not can_browse(adapter):
            return []

        needed = [field for field in spec.browse_fields if field not in (scope or {})]
        if needed:
            raise ScopeRequired(resource_type, needed)
        return cast("Browsable", adapter).browse(self.probe(resource_type, scope), self, limit)

    def probe(self, resource_type: str, scope: dict[str, Any] | None = None) -> Node:
        """A node that exists only to carry a type's config to an adapter, with no instance behind it."""
        return Node(
            id=f"{resource_type}.*",
            collection="",
            name="*",
            spec=self.spec(resource_type),
            body=dict(scope or {}),
        )

    def find_existing(self, node: Node) -> Record | None:
        if node.ephemeral:
            return None
        adapter = self.adapters.get(node.system)
        if adapter is None:
            return None
        try:
            return adapter.find(node, self)
        except Unresolved:
            return None

    def status(self, collection: str | None = None) -> Statuses:
        self._ids.clear()
        self.invalidate_cache()
        out: dict[str, ResourceStatus] = {}
        for nid, node in sorted(self.nodes.items()):
            if collection is not None and node.collection != collection:
                continue
            out[nid] = self._status_of(node)
        return Statuses(out)

    def _status_of(self, node: Node) -> ResourceStatus:
        if node.system not in self.adapters:
            return ResourceStatus(UNSUPPORTED, f"no adapter for system {node.system!r} in env {self.env}")
        if node.ephemeral:
            return ResourceStatus(EPHEMERAL, "built per run")
        try:
            record = self.find_existing(node)
        except Exception as exc:
            return ResourceStatus(ERROR, _short(exc))
        if record is None:
            return ResourceStatus(ABSENT)
        identity = record.get(node.id_field)
        self._ids[node.id] = identity
        return ResourceStatus(PRESENT, identity=identity, record=record)

    # ---- writes -----------------------------------------------------------

    def provisionable(self, node_id: str) -> tuple[bool, str]:
        """Whether provisioning this node can create it, and why not when it cannot.

        Callers offering a "create it" action ask first: attempting either of these can only
        report the same refusal back, so the honest UI never offers the button.
        """
        node = self.node(node_id)
        if node.mode == REFERENCE:
            return False, "reference resources must already exist in the environment — ATF never creates them"
        if node.mode == DATA:
            return False, "an observation, not a resource ATF makes — there is nothing here to create"
        if node.ephemeral:
            return False, "built fresh for every run by the test that needs it"
        return True, ""

    def materialize(
        self,
        subset: Iterable[str],
        keep_going: bool = False,
        on_start: Callable[[str], None] | None = None,
        on_result: Callable[[ProvisionResult], None] | None = None,
        overrides: Mapping[str, Record] | None = None,
        fresh: str = "",
    ) -> ProvisionOutcome:
        """Provision `subset` and everything it depends on, dependency-first.

        Stops at the first failure by default: provisioning failures are usually correlated (a bad
        token, an unreachable backend), so continuing turns one clear error into many identical
        ones. With `keep_going`, a failed node's dependents are reported `blocked` and independent
        subtrees are still attempted — useful when seeding a whole catalog.

        `on_start` and `on_result` observe the pass as it happens, node by node, for a caller
        showing progress; they see exactly the entries the return value collects.

        `fresh` names the one node this pass must *make* rather than look up, whatever its
        lifecycle. Every other node is provisioned as it always is — found-or-created and shared —
        with one exception: a node this scenario already has an instance of its own of is handed
        that instance back rather than looked up again. That is what lets a chain of them be written
        a line per link, a fresh list hanging off the fresh owner this scenario made rather than off
        the shared one. It also settles what a plain `Given the …` means *after* a fresh one in the
        same scenario: the one you already have. Provisioning the shared resource as well would
        leave the scenario holding two of a thing it named once.
        """
        # A listing is memoised for the duration of one pass, not the session: the materializer is
        # session-scoped, and the system under test mutates the same backend between passes.
        self._ids.clear()
        self.invalidate_cache()
        results: list[ProvisionResult] = []
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
            blocker = next((dep for dep in node.depends_on if dep in stalled), None)
            if blocker is not None:
                blocked = ProvisionResult(
                    nid, BLOCKED, ok=False, detail=f"depends on {blocker}, which did not provision"
                )
                results.append(blocked)
                stalled.add(nid)
                _notify(on_result, blocked)
                continue

            _notify(on_start, nid)
            held = None if nid == fresh else self._fresh.get(nid)
            if held is not None:
                # This scenario already has one of these of its own, and a dependent asking for the
                # shared one behind its back would be the isolation quietly not happening.
                outcome = ProvisionResult(nid, EXISTS, ok=True, record=held[1])
            else:
                outcome = self._attempt(node, (overrides or {}).get(nid), fresh=nid == fresh)
            results.append(outcome)
            if outcome.ok:
                record = outcome.record or {}
                self._ids[nid] = record.get(node.id_field)
                records[nid] = record
                _notify(on_result, outcome)
                continue

            stalled.add(nid)
            _notify(on_result, outcome)
            if not keep_going:
                break

        return ProvisionOutcome(results=results, records=records)

    def _attempt(self, node: Node, overrides: Record | None = None, fresh: bool = False) -> ProvisionResult:
        """Provision one node. Returns a result carrying `record` when it succeeded."""
        nid = node.id
        adapter = self.adapters.get(node.system)
        if adapter is None:
            detail = f"no adapter for system {node.system!r} in env {self.env}"
            return ProvisionResult(nid, UNSUPPORTED, ok=False, detail=detail)

        try:
            record, action = self._provision(node.varied_with(overrides), adapter, fresh)
        except Exception as exc:  # noqa: BLE001 - reported, not raised: callers read `results`
            return ProvisionResult(nid, ERROR, ok=False, detail=_short(exc))

        if record is None:
            # An absent observation is an answer, not a failure: `data` says "look at this", and
            # "it is not there" is one of the things a scenario may want to claim about it.
            if node.mode == DATA:
                return ProvisionResult(nid, OBSERVED, ok=True, record={})
            return ProvisionResult(nid, action, ok=False, detail="reference resource not found")
        return ProvisionResult(nid, action, ok=True, record=record)

    def _provision(self, node: Node, adapter: Adapter, fresh: bool = False) -> tuple[Record | None, str]:
        if node.mode == DATA:
            return adapter.find(node, self), OBSERVED
        if node.mode == REFERENCE:
            return adapter.find(node, self), REFERENCE

        # An isolated instance is not looked up, for the same reason an ephemeral one is not: the
        # lookup would find the shared resource and hand back the very thing being isolated from.
        existing = None if fresh or node.ephemeral else adapter.find(node, self)
        if existing is not None:
            return existing, EXISTS

        body = self.resolve(node.body)
        record = adapter.create(node, body, self)
        self.invalidate_cache()
        return record, CREATED

    # ---- acting on one ----------------------------------------------------

    def act(self, node: Node, record: Record, action: str) -> Record | None:
        """Do something to a resource that is already there.

        `delete` is ATF's own, because every adapter has one — a backend without deletion no-ops it
        through `NoopDelete`, and the scenario after it reads the resource back and finds out.
        Every other action is one the catalog declared and the adapter interprets.
        """
        adapter = self.adapters.get(node.system)
        if adapter is None:
            raise ProvisioningError(node.id, f"no adapter for system {node.system!r} in env {self.env}")

        if action in BUILT_IN_ACTIONS:
            adapter.delete(node, record, self)
            self.invalidate_cache()
            return None

        if not can_act(adapter):
            raise ProvisioningError(
                node.id,
                f"the {node.system!r} adapter can make a resource and remove one, and nothing "
                "else — give it an `act` to reach the actions this type declares",
            )
        result = cast("Actionable", adapter).act(node, record, action, self)
        # Whatever it did, the listing behind the cache was read before it happened.
        self.invalidate_cache()
        return result

    def create_closure(
        self, nid: str, keep_going: bool = False, overrides: Mapping[str, Record] | None = None
    ) -> ProvisionOutcome:
        return self.materialize(self.closure(nid), keep_going=keep_going, overrides=overrides)

    def create_all(self, keep_going: bool = False) -> ProvisionOutcome:
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
        return self._ensured(nid, outcome)

    def _ensured(self, nid: str, outcome: ProvisionOutcome) -> tuple[Record, dict[str, Record]]:
        failure = next(iter(outcome.failures), None)
        if failure is not None:
            raise ProvisioningError(failure.node_id, failure.detail)
        records = outcome.records
        record = records.get(nid)
        if record is None:
            raise ProvisioningError(nid, "adapter returned no record")
        return record, records

    # ---- one scenario's own ------------------------------------------------

    def ensure_fresh(
        self, resource_type: str, name: str, overrides: Record | None = None
    ) -> tuple[Record, dict[str, Record]]:
        """An instance of a catalog node that belongs to this scenario, and is taken away with it.

        The same closure as `ensure_closure`, with one node made instead of found. Its dependencies
        are *not* made afresh — see `materialize` — because the mix is the point: the expensive
        scaffolding stays shared and seeded once, and only what a scenario needs to itself is built
        per scenario. Cascading would be the all-or-nothing model this exists to escape.

        Two questions this deliberately does not answer are the step's, because the step is where
        the sentence a person reads is written: whether the node is one ATF can create at all
        (`provisionable`), and whether it can be told apart from the shared one
        (`key_of_its_own`). Called with neither asked, this still does the honest thing — it creates
        a second resource — and the caller has simply not said what makes it a second one.
        """
        nid = self.resolve_id(resource_type, name)
        written = dict(overrides or {})
        varied = {**self._own_key(self.node(nid), written), **written}
        outcome = self.materialize(self.closure(nid), overrides={nid: varied} if varied else None, fresh=nid)
        record, records = self._ensured(nid, outcome)
        # Kept unresolved, as the catalog writes bodies: the `${uuid…}` in the key resolves through
        # this scenario's memo, so every later read of this node resolves to the same instance and
        # the claims about it need to know nothing about any of this.
        self._fresh[nid] = (self.node(nid).varied_with(varied), record)
        return record, records

    def made_fresh(self, nid: str) -> Node | None:
        """This node as this scenario made it its own — the key it was given — or nothing.

        What a claim resolves against. A step reading the catalog node instead would go looking for
        the shared resource and make a claim about somebody else's.
        """
        held = self._fresh.get(nid)
        return None if held is None else held[0]

    def key_of_its_own(self, node: Node) -> tuple[list[str], str]:
        """The natural-key fields an isolated instance can be told apart by, and why there are none.

        A field holding a `${...}` that names another node is left out: that is the link to this
        resource's parent, and a copy pointing at nothing is not a copy of anything. A field that is
        not text is left out too — appending to a number would quietly change what kind of thing the
        backend is being sent.
        """
        keys = node.natural_keys
        if not keys:
            return [], f"{node.resource} declares no natural key, so nothing tells two of them apart"
        mine = [key for key in keys if _is_own_text(node.body.get(key))]
        if not mine:
            return [], (
                f"every field a {node.resource} is known by ({', '.join(keys)}) is either a link "
                "to another resource or not text, so a copy could not be told from the shared one"
            )
        return mine, ""

    def _own_key(self, node: Node, written: Record) -> Record:
        """The key fields to write differently so this instance is nobody else's.

        One discriminator per fresh instance, from the provider a person would reach for themselves.
        The `#` part is what keeps two of them apart within one scenario: a provider call is
        evaluated once per scenario per expression, which is exactly what makes the *same* fresh
        instance keep its key from the `Given` that made it to the last claim about it.
        """
        mine, _ = self.key_of_its_own(node)
        wanted = [key for key in mine if key not in written]
        if not wanted:
            return {}
        self._isolated += 1
        tag = str(self.resolve(f"${{uuid:hex#{node.id}/{self._isolated}}}"))[:FRESH_TAG]
        return {key: f"{node.body[key]}{FRESH_MARK}{tag}" for key in wanted}

    def ephemeral_records(self, records: Mapping[str, Record]) -> list[tuple[str, Record]]:
        return [
            (nid, record)
            for nid, record in records.items()
            if nid in self.nodes and self.nodes[nid].ephemeral
        ]

    def close(self) -> None:
        """Release every adapter's resources. Safe to call more than once."""
        for adapter in self.adapters.values():
            close_adapter(adapter)

    def teardown(self, records: Mapping[str, Record] | Iterable[tuple[str, Record]]) -> None:
        """Best-effort delete of what this scenario built for itself. Never raises.

        Accepts pairs as well as a mapping, because one scenario can provision several instances
        of the same ephemeral node — each is a distinct record that has to be deleted.

        Two kinds of resource are taken away: an ephemeral one, and an instance of a persistent node
        this scenario asked to have to itself. Nothing else, ever — the guard is what keeps a
        shared resource from being deleted by a scenario that merely used it.
        """
        source: Any = records.items() if isinstance(records, Mapping) else records
        pairs: list[tuple[str, Record]] = [(str(nid), record) for nid, record in source]
        for nid, record in pairs:
            node = self.made_fresh(nid) or self.nodes.get(nid)
            if node is None or (not node.ephemeral and nid not in self._fresh):
                continue
            adapter = self.adapters.get(node.system)
            if adapter is None:
                continue
            try:
                adapter.delete(node, record, self)
            except Exception as exc:
                log.warning("teardown of %s failed: %s", nid, _short(exc))


def _is_own_text(value: Any) -> bool:
    """Whether a body field is text this resource holds of its own, rather than a link elsewhere."""
    return isinstance(value, str) and bool(value) and not references(value)


def _notify(callback: Callable[[_T], None] | None, value: _T) -> None:
    if callback is not None:
        callback(value)


def _short(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    first = text.splitlines()[0]
    return first if len(first) <= 200 else first[:197] + "..."
