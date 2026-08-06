"""What one test is holding while it runs: what it arranged, and what its actions produced.

This is **not** the scratchpad that used to be here. The old `spec/context.py` was a second way to
arrange things, alongside the declarations — which is exactly what `one-engine-two-surfaces` exists
to remove. Slots survive as a concept in the Act band; the object that also provisioned does not.

Everything arranged goes through the same engine a pytest fixture goes through. A scenario asking for
`the todo_list "groceries"` and a function taking `groceries: TodoList` reach the same
[reconcile.ensure](reconcile.py), which is the whole claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import graph, reconcile
from .declare import Instance, declaration_of, instance_of
from .environment import Ground
from .loader import Suite, fixture_name
from .spi import Record, State

NULL = "null"


class ScopeError(Exception):
    """Raised when a scenario asks for something it did not arrange, or arranged twice."""


@dataclass
class Scope:
    """One test's holdings. Made fresh per test, and never shared between two."""

    suite: Suite
    ground: Ground
    made: list[Any] = field(default_factory=list)
    # The run's ledger, shared by every test in it. A `session` resource is made by whichever test
    # needed it first and removed when the run ends, so what made it cannot be what remembers it.
    run: list[Any] = field(default_factory=list)
    slots: dict[str, Any] = field(default_factory=dict)
    arranged: list[Any] = field(default_factory=list)
    pending: Any = None

    # --- Arranging ---------------------------------------------------------------------------

    def arrange(self, kind: str, name: str, patch: dict[str, str] | None = None) -> Any:
        """Make that resource and everything its lineage needs, and hold it in scope.

        A varied one is **held back**, not made yet. `Given ... but "slug" is "weekly"` may be
        followed by `And "owner" is "null"`, and a variation is one resource with several fields
        changed — not one resource made once per sentence. It lands when anything reads it.
        """
        self.flush()
        declared = self._declared(kind, name)
        if patch:
            self.pending = varied(declared, patch)
            return self.pending
        return self._provision(declared)

    def flush(self) -> Any:
        """Make whatever a variation has been accumulating, once nothing more can be added to it."""
        if self.pending is None:
            return None
        resource, self.pending = self.pending, None
        return self._provision(resource)

    def arrange_any(self, kind: str) -> Any:
        """Any resource of that kind — one already in scope, or one the factory builds."""
        self.flush()
        existing = self.in_scope(kind)
        if existing:
            return existing[0]
        cls = self._kind(kind)
        factory = getattr(cls, "factory", None)
        if factory is None:
            raise ScopeError(
                f"a {kind} was asked for, nothing is in scope, and {cls.__name__} has no factory — "
                f"name the one you mean"
            )
        built = factory(**{fixture_name(need.__name__): self.arrange_any(fixture_name(need.__name__))
                           for need in declaration_of(cls).kinds_needed})
        instance_of(built).from_factory = True
        return self._provision(built)

    def vary(self, field_name: str, value: str) -> Any:
        """One more field of whatever the previous `Given` named — the continuation sentence.

        MIGRATION.md §1.6 asks for the parse rule. This is it: the line carries no subject, so it
        continues the resource the last `Given` named, and it is an error rather than a guess when
        no such line came before it.
        """
        if self.pending is None:
            raise ScopeError(
                f'"{field_name}" is "{value}" continues a varied resource, and the sentence before '
                f'it named none. Write `Given the <kind> "<name>" but "{field_name}" is "{value}"`.'
            )
        self.pending = varied(self.pending, {field_name: value})
        return self.pending

    def _provision(self, resource: Any) -> Any:
        if no_make():
            return self._require_present(resource)
        for outcome in reconcile.provision(self.ground, [resource]):
            if outcome.state is State.UNREACHABLE:
                raise ScopeError(f"{outcome.name}: {outcome.why}")
            if outcome.state is State.ABSENT and declaration_of(outcome.resource).when_absent == "require":
                raise ScopeError(f"{outcome.name}: {outcome.why}")
            if not any(node is outcome.resource for node in self.made):
                self.made.append(outcome.resource)
            if not any(node is outcome.resource for node in self.run):
                self.run.append(outcome.resource)
        for node in graph.closure(resource):
            if not any(held is node for held in self.arranged):
                self.arranged.append(node)
        return resource

    def _require_present(self, resource: Any) -> Any:
        """`--no-make`: read what is there, and fail the test on anything that is not.

        The closure is walked all the same, because a parent missing is why a child is missing.
        """
        for node in graph.closure(resource):
            state, _ = self.ground.find(node)
            if state is not State.PRESENT:
                raise ScopeError(
                    f"{instance_of(node).name or declaration_of(node).kind} is {state}, "
                    f"and this run was told not to make anything"
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
            names = ", ".join(sorted(instance_of(node).name or "one the factory built" for node in found))
            raise ScopeError(f"{len(found)} of kind {kind} are in scope — {names}. Ask for the one you mean by name.")
        return found[0] if found else self.arrange_any(kind)

    def look_up(self, kind: str, name: str) -> Record | None:
        """Ask the environment for that resource's record, right now."""
        self.flush()
        resource = self._in_scope_named(name) or self._declared(kind, name)
        _, found = self.ground.find(resource)
        return found

    def act(self, kind: str, name: str, action: str) -> Any:
        self.flush()
        resource = self._in_scope_named(name) or self._declared(kind, name)
        return self.remember("result", reconcile.act(self.ground, resource, action))

    def browse(self, kind: str) -> list[Record]:
        self.flush()
        cls = self._kind(kind)
        example = next((node for node in self.arranged if type(node) is cls), None)
        if example is None:
            example = next((node for node in self.suite.instances.values() if type(node) is cls), None)
        if example is None:
            raise ScopeError(f"nothing of kind {kind} is declared, so there is nothing to list")
        return reconcile.browse(self.ground, example)

    # --- Slots -------------------------------------------------------------------------------

    def remember(self, slot: str, value: Any) -> Any:
        self.slots[slot] = value
        return value

    def recall(self, slot: str) -> Any:
        try:
            return self.slots[slot]
        except KeyError:
            known = ", ".join(sorted(self.slots)) or "nothing yet"
            raise ScopeError(f"no {slot!r} — this test has produced {known}") from None

    # --- Lookups ------------------------------------------------------------------------------

    def _kind(self, kind: str) -> type:
        for name, cls in self.suite.kinds.items():
            if fixture_name(name) == kind or name == kind:
                return cls
        known = ", ".join(sorted(fixture_name(name) for name in self.suite.kinds)) or "none"
        raise ScopeError(f"no resource kind called {kind!r} (declared: {known})")

    def _declared(self, kind: str, name: str) -> Any:
        resource = self.suite.instances.get(name)
        if resource is None:
            known = ", ".join(sorted(self.suite.instances)) or "none"
            raise ScopeError(f'no resource called "{name}" (declared: {known})')
        if type(resource) is not self._kind(kind):
            raise ScopeError(f'"{name}" is a {declaration_of(resource).kind}, and the sentence says {kind}')
        return resource

    def _in_scope_named(self, name: str) -> Any:
        return next((node for node in self.arranged if instance_of(node).name == name), None)


def varied(resource: Any, patch: dict[str, str]) -> Any:
    """A copy of a resource with one or more fields changed, for the length of one scenario.

    The patch is applied **before** recognition, so patching a recognised field names a different
    resource rather than renaming the one declared. `"null"` removes the field, and removing one
    that carries lineage drops that edge — which is how a test about a list with no owner is written.

    **Patching a recognised field makes the copy function-scoped**, whatever the declaration says.
    A new resource that nothing declared and nothing removes fills the environment a row per run,
    and it is not a leak anything catches: a `persistent` resource is supposed to survive. Patching
    any other field adjusts the resource already there, and leaves its lifetime alone.
    """
    original: Instance = instance_of(resource)
    values = dict(original.values)
    explicit = [parent for parent in original.depends_on if not any(parent is v for v in values.values())]

    for name, written in patch.items():
        if written == NULL:
            values.pop(name, None)
        else:
            values[name] = written

    copy = type(resource)(**values, depends_on=explicit)
    record = instance_of(copy)
    record.name = original.name
    record.from_factory = original.from_factory
    record.ephemeral = original.ephemeral or bool(set(patch) & set(declaration_of(resource).unique_by))
    record.varied = original.varied | frozenset(patch)
    return copy


def no_make() -> bool:
    """Whether this run was told not to make anything — `atf run --no-make`."""
    from . import plugin

    return bool(getattr(plugin, "NO_MAKE", False))


_CURRENT: Scope | None = None


def start(scope: Scope) -> Scope:
    """Make this the scope steps and fixtures read. One test at a time, always."""
    global _CURRENT  # noqa: PLW0603 - one running test is one process-wide fact
    _CURRENT = scope
    return scope


def finish() -> None:
    global _CURRENT  # noqa: PLW0603
    _CURRENT = None


def current() -> Scope | None:
    return _CURRENT


def require() -> Scope:
    scope = current()
    if scope is None:
        raise ScopeError("no test is running, so there is nothing in scope")
    return scope

