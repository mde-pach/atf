"""What one test is holding while it runs, and the one resolver that fills every hole."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import graph, lives, reconcile
from .declare import (
    Instance,
    Need,
    declaration_of,
    instance_of,
    is_declared,
    is_resource,
    resolver_wants,
)
from .environment import Ground
from .loader import Suite, fixture_name
from .spi import Payload, State


class ScopeError(Exception):
    """Raised when a scenario asks for something it did not arrange, or arranged twice."""


class ResolutionError(Exception):
    """Raised when a `needs()` cannot be answered, naming the hole and what was tried."""


@dataclass
class Scope:
    """One test's holdings. Made fresh per test, and never shared between two."""

    suite: Suite
    ground: Ground
    made: list[Any] = field(default_factory=list)
    # The run's ledger, shared by every test in it. Something living for the run is made by
    # whichever test needed it first and removed when the run ends, so what made it cannot be what
    # remembers it.
    run: list[Any] = field(default_factory=list)
    #: What the last action produced. `it` reads this; `the previous` reads the one before it.
    happened: list[Any] = field(default_factory=list)
    arranged: list[Any] = field(default_factory=list)
    pending: Any = None
    #: Resources this test changed, so what it changed can be put back when the test ends.
    acted: list[Any] = field(default_factory=list)
    #: Which fields it wrote on each of them, by resource identity.
    loosed: dict[int, set[str]] = field(default_factory=dict)
    #: What resolution is inside, innermost last. A name already here is a cycle.
    resolving: list[str] = field(default_factory=list)

    # --- Arranging ---------------------------------------------------------------------------

    def arrange(self, kind: str, name: str, patch: dict[str, str] | None = None) -> Any:
        """Make that resource and everything its lineage needs, and hold it in scope.

        A varied one is **held back**, not made yet. `Given the list "groceries" with slug "weekly"`
        may be followed by another field, and a variation is one resource with several fields
        changed — not one resource made once per sentence. It lands when anything reads it.
        """
        self.flush()
        declared = self._declared(kind, name)
        if patch:
            self.pending = self.varied(declared, patch)
            return self.pending
        return self._provision(self.resolve(declared))

    def flush(self) -> Any:
        """Make whatever a variation has been accumulating, once nothing more can be added to it."""
        if self.pending is None:
            return None
        resource, self.pending = self.pending, None
        return self._provision(self.resolve(resource))

    def a(self, kind: str, patch: dict[str, Any] | None = None) -> Any:
        """Any of that kind — one already in scope, or one resolution builds.

        `patch` is what `Given a list with slug "produce"` gives the resolver: the fields the
        scenario cares about, with the rest resolved. Variation was never more than that.
        """
        self.flush()
        if patch:
            built = self._kind(kind)(**patch)
            instance_of(built).built = True
            return self._provision(self.resolve(built))
        return self.of_kind(self._kind(kind))

    def vary(self, field_name: str, value: Any) -> Any:
        """One more field of whatever the previous `Given` named — the continuation sentence."""
        if self.pending is None:
            raise ScopeError(
                f'"{field_name}" is "{value}" continues a varied resource, and the sentence before '
                f"it named none."
            )
        self.pending = self.varied(self.pending, {field_name: value})
        return self.pending

    # --- Resolution: the one mechanism -----------------------------------------------------------

    def resolve(self, resource: Any) -> Any:
        """Fill every hole this thing left to `needs()`, and every hole in what it holds.

        A parent written in by hand has holes of its own, and provisioning walks the whole closure —
        so resolution has to walk it too, or something is made before it is finished.

        Nothing is touched here. Resolution decides *what* a thing is; provisioning is what makes it
        exist, and it reads the graph resolution just finished writing.
        """
        record = instance_of(resource)
        declaration = declaration_of(resource)
        where = record.name or declaration.kind
        if where in self.resolving:
            way_round = " -> ".join([*self.resolving, where])
            raise ResolutionError(f"a thing cannot need itself: {way_round}")
        self.resolving.append(where)
        try:
            for one in list(record.depends_on):
                self.resolve(one)
            for field_name, need in declaration.needs.items():
                if field_name in record.values or field_name in record.dropped:
                    continue
                value = self._produce(need, resource)
                record.values[field_name] = value
                record.resolved.add(field_name)
                setattr(resource, field_name, value)
                if is_resource(value) and not any(one is value for one in record.depends_on):
                    record.depends_on.append(value)
        finally:
            self.resolving.pop()
        return resource

    def _produce(self, need: Need, filling: Any = None) -> Any:
        """One hole, filled. A kind is built; anything else is called."""
        if need.kind is not None:
            return self.of_kind(need.kind, filling)
        return self._call(need.resolver, need.where, filling)

    def _call(self, resolver: Any, where: str, filling: Any = None) -> Any:
        """Call whatever `needs(...)` named, supplying what it asks for.

        **A dependency may depend on things**, which is the whole power of the pattern and what
        makes a factory unnecessary. A resolver's parameters are answered the same way a step's
        are: a declared kind, a declared thing by name, or a system by name.
        """
        arguments: dict[str, Any] = {}
        for name, annotation in resolver_wants(resolver).items():
            if is_declared(annotation):
                arguments[name] = self.of_kind(annotation, filling)
            elif name in self.suite.instances:
                arguments[name] = self._provision(self.resolve(self.suite.resource(name)))
            elif name in self.ground.drivers:
                arguments[name] = self.ground.drivers[name]
            elif (cls := self._kind_or_none(name)) is not None:
                arguments[name] = self.of_kind(cls)
            else:
                raise ResolutionError(
                    f"{where}: resolving it calls {getattr(resolver, '__name__', resolver)!r}, "
                    f"which asks for {name!r}, and nothing declares it.\n"
                    f"  It is not a kind, not a declared thing, and not a system."
                )
        try:
            return resolver(**arguments)
        except Exception as exc:
            raise ResolutionError(
                f"{where}: resolving it raised {type(exc).__name__}: {exc}"
            ) from exc

    def of_kind(self, cls: type, filling: Any = None) -> Any:
        """One of this kind: whichever is already to hand, or one resolution builds.

        This is what a scenario saying `Given a list` reaches, what a Python test signature saying
        `other: TodoList = needs()` reaches, and what a resolver taking `owner: Owner` reaches.
        One path, so one object and one lifetime.

        `filling` is the thing whose hole is being filled, and **its own lineage answers first**: a
        resolver for `TodoList.slug` that takes an `Owner` means *this list's* owner, not any owner
        at all. Reaching past what is in front of you would be how a resolver quietly builds a
        second one.
        """
        if filling is not None:
            held = [one for one in instance_of(filling).depends_on if type(one) is cls]
            if held:
                return held[0]
        found = [node for node in self.arranged if type(node) is cls]
        if found:
            return found[0]
        built = cls()
        instance_of(built).built = True
        return self._provision(self.resolve(built))

    # --- Provisioning ---------------------------------------------------------------------------

    def _provision(self, resource: Any) -> Any:
        if no_make():
            return self._require_present(resource)
        for outcome in reconcile.provision(self.ground, [resource]):
            if outcome.state is State.UNREACHABLE:
                raise ScopeError(f"{outcome.name}: {outcome.why}")
            if outcome.state is State.ABSENT:
                # A thing *they* own is not made, and a scenario that asked for it needs it. The
                # difference between requiring and merely observing belongs here, with the asking.
                raise ScopeError(
                    f"{outcome.name} is not there, and {self.ground.config.name} is not ATF's to "
                    f"make it in: {outcome.why}"
                )
            if not any(node is outcome.resource for node in self.made):
                self.made.append(outcome.resource)
            if not any(node is outcome.resource for node in self.run):
                self.run.append(outcome.resource)
        for node in graph.closure(resource):
            if not any(held is node for held in self.arranged):
                self.arranged.append(node)
        return resource

    def _require_present(self, resource: Any) -> Any:
        """`--no-make`: read what is there, and fail the test on anything that is not."""
        for node in graph.closure(resource):
            state, _ = self.ground.find(node)
            if state is not State.PRESENT:
                raise ScopeError(
                    f"{lives.named(node)} is {state}, and this run was told not to make anything"
                )
            if not any(held is node for held in self.arranged):
                self.arranged.append(node)
        return resource

    # --- Reading what is in scope -------------------------------------------------------------

    def in_scope(self, kind: str) -> list[Any]:
        """Everything of that kind this test arranged, in the order it arranged them."""
        self.flush()
        cls = self._kind(kind)
        return [node for node in self.arranged if type(node) is cls]

    def the(self, kind: str) -> Any:
        """The one of that kind in scope. Two is an error, and it is caught at collection."""
        found = self.in_scope(kind)
        if len(found) > 1:
            names = ", ".join(sorted(lives.named(node) for node in found))
            raise ScopeError(
                f"{len(found)} of kind {kind} are in scope — {names}. Ask for the one you mean by name."
            )
        return found[0] if found else self.a(kind)

    def look_up(self, kind: str, name: str) -> Payload | None:
        """Ask the environment for that resource's record, right now."""
        self.flush()
        resource = self._in_scope_named(name) or self.resolve(self._declared(kind, name))
        _, found = self.ground.find(resource)
        return found

    def change(self, kind: str, name: str, changes: Payload) -> Any:
        """Write fields onto a resource mid-test, and remember which ones so they can be put back."""
        self.flush()
        resource = self._in_scope_named(name) or self.resolve(self._declared(kind, name))
        if not any(node is resource for node in self.acted):
            self.acted.append(resource)
        self.loosed.setdefault(id(resource), set()).update(changes)
        return self.remember(reconcile.change(self.ground, resource, changes))

    def browse(self, kind: str) -> list[Payload]:
        self.flush()
        cls = self._kind(kind)
        example = next((node for node in self.arranged if type(node) is cls), None)
        if example is None:
            example = next((node for node in self.suite.instances.values() if type(node) is cls), None)
        if example is None:
            raise ScopeError(f"nothing of kind {kind} is declared, so there is nothing to list")
        return reconcile.browse(self.ground, example)

    # --- What happened -------------------------------------------------------------------------

    def remember(self, value: Any) -> Any:
        """Keep what an action produced. `it` is whatever last happened, and nothing names it."""
        self.happened.append(value)
        return value

    def it(self) -> Any:
        """Whatever last happened.

        Assert before you act again and you never need a slot. A scenario is a sequence, and people
        describe sequences by interleaving — `Then` may follow `When` more than once.
        """
        if not self.happened:
            raise ScopeError(
                "`it` is whatever last happened, and nothing has happened in this scenario yet.\n"
                "  Write a `When` above this line."
            )
        return self.happened[-1]

    def previous(self) -> Any:
        """The one before `it`, for the rare scenario genuinely holding two results at once."""
        if len(self.happened) < 2:
            said = "nothing" if not self.happened else "only one thing"
            raise ScopeError(
                f"`the previous` is what happened before `it`, and {said} has happened here.\n"
                f"  A scenario juggling three results at once should have been two scenarios."
            )
        return self.happened[-2]

    # --- Variation ------------------------------------------------------------------------------

    def varied(self, resource: Any, patch: dict[str, str]) -> Any:
        """A copy of a resource with one or more fields changed, for the length of one scenario.

        The patch is applied **before** recognition, so patching a recognised field names a
        different thing. **That makes the copy live for the test**, whatever the span would
        otherwise be. Patching any other field leaves the lifetime alone.
        """
        original: Instance = instance_of(resource)
        values = dict(original.values)

        dropped = set(original.dropped)
        for name, written in patch.items():
            # `without a slug` is written as nothing at all, and removing a field that held a
            # parent drops that edge with it. Resolution does not put one of these back.
            if written is None:
                values.pop(name, None)
                dropped.add(name)
            else:
                values[name] = written
                dropped.discard(name)

        copy = type(resource)(**values)
        record = instance_of(copy)
        record.name = original.name
        record.built = original.built
        record.resolved = set(original.resolved) - set(patch)
        record.dropped = frozenset(dropped)
        recognised = set(declaration_of(resource).key)
        record.ephemeral = original.ephemeral or bool(set(patch) & recognised)
        record.varied = original.varied | frozenset(patch)
        return copy

    # --- Lookups ------------------------------------------------------------------------------

    def _kind_or_none(self, kind: str) -> type | None:
        for name, cls in self.suite.kinds.items():
            if fixture_name(name) == kind or name == kind:
                return cls
        return None

    def _kind(self, kind: str) -> type:
        cls = self._kind_or_none(kind)
        if cls is not None:
            return cls
        known = ", ".join(sorted(fixture_name(name) for name in self.suite.kinds)) or "none"
        raise ScopeError(f"no kind called {kind!r} (declared: {known})")

    def _declared(self, kind: str, name: str) -> Any:
        resource = self.suite.instances.get(name)
        if resource is None:
            known = ", ".join(sorted(self.suite.instances)) or "none"
            raise ScopeError(f'nothing called "{name}" (declared: {known})')
        if type(resource) is not self._kind(kind):
            raise ScopeError(f'"{name}" is a {declaration_of(resource).kind}, and the sentence says {kind}')
        return resource

    def _in_scope_named(self, name: str) -> Any:
        return next((node for node in self.arranged if instance_of(node).name == name), None)


def no_make() -> bool:
    """Whether this run was told not to make anything — `atf run --no-make`."""
    from . import plugin

    return bool(getattr(plugin, "NO_MAKE", False))


_CURRENT: Scope | None = None


def start(scope: Scope) -> Scope:
    """Make this the scope steps and fixtures read. One test at a time, always."""
    global _CURRENT
    _CURRENT = scope
    return scope


def finish() -> None:
    global _CURRENT
    _CURRENT = None
