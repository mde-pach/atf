"""Reconciliation: what ATF does with the answer recognition gave it.

```text
find  →  nothing        → create(resource)
      →  same           → done
      →  differs        → update(resource, found, changes)
```

**ATF computes the diff, never the adapter.** `changes` reaches the adapter already worked out, and
the adapter's job is to apply it — which is what lets the editor show what pressing the button
*would* alter, field by field, before anything is pressed.

**A declaration is a partial specification.** The fields you named must hold; fields you did not
name are left alone, so a `created_at` the system set and a colour somebody picked in the product
survive untouched. The cost is the other side of that: an undeclared field can drift to anything and
ATF will neither correct it nor mention it.

## What counts as different

This is the loosest part of ATF and it is loose on purpose. `compare.matches` treats `"1"` and `1`
as the same value, and two spellings of one instant as one instant, because a system that returns an
id as a string where the declaration wrote a number has still returned the right thing.

Tightening it would make every run write to the real environment over a difference that is not one.
Loosening it would leave real drift uncorrected. It lands on shared environments where a wrong
answer is expensive, so the rule is stated here rather than buried: **a field differs when
`compare.matches` says the found value is not the declared one.**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import graph
from .declare import Unreachable, declaration_of, instance_of, is_resource, name_of, values_of
from .environment import Ground
from .model import compare
from .spi import Did, Record, State


class ProvisionError(Exception):
    """Raised when a resource cannot be brought to what its declaration says."""


@dataclass(frozen=True)
class Outcome:
    """What one pass did to one resource, and what the environment holds now."""

    resource: Any
    state: State
    did: Did
    record: Record | None = None
    changes: Record = field(default_factory=dict)
    why: str = ""

    @property
    def name(self) -> str:
        return name_of(self.resource) or declaration_of(self.resource).kind


def declared_values(resource: Any) -> Record:
    """The fields ATF compares and writes: everything declared that is not another resource.

    A field holding a parent is left out on purpose. What a parent means in the child's row — a
    foreign key, an embedded document, a path segment — is the system's business, and the adapter
    is the only thing that knows. The cost is that a changed parent is not reconciled by this diff.
    """
    return {name: value for name, value in values_of(resource).items() if not is_resource(value)}


def diff(resource: Any, found: Record) -> Record:
    """The declared fields the found record does not already satisfy."""
    return {
        name: value
        for name, value in declared_values(resource).items()
        if not compare.matches(found.get(name, None), value)
    }


def ensure(ground: Ground, resource: Any, *, dry_run: bool = False) -> Outcome:
    """Bring one resource to what its declaration says, and report what that took.

    Only this resource. Everything it needs is [closure](graph.py)'s job, and `provision` walks that.
    """
    declaration = declaration_of(resource)
    state, found = ground.find(resource)

    if state is State.UNREACHABLE:
        return Outcome(resource, state, Did.LEFT_ALONE, why=f"the {declaration.system} system could not be reached")

    if state is State.PRESENT and found is not None:
        changes = diff(resource, found)
        if not changes:
            return Outcome(resource, State.PRESENT, Did.UNCHANGED, record=found)
        if not ground.mutable:
            return Outcome(
                resource,
                State.PRESENT,
                Did.LEFT_ALONE,
                record=found,
                changes=changes,
                why=f"the {ground.config.name} environment is not mutable",
            )
        if declaration.when_absent == "observe":
            return Outcome(resource, State.PRESENT, Did.LEFT_ALONE, record=found, changes=changes, why="observe")
        if dry_run:
            return Outcome(resource, State.PRESENT, Did.UPDATED, record=found, changes=changes, why="dry run")
        return Outcome(
            resource,
            State.PRESENT,
            Did.UPDATED,
            record=_apply(ground, resource, found, changes),
            changes=changes,
        )

    # Absent from here down.
    if declaration.when_absent == "require":
        return Outcome(
            resource,
            State.ABSENT,
            Did.LEFT_ALONE,
            why=f"it is declared `when_absent=\"require\"`, and {ground.config.name} does not have it",
        )
    if declaration.when_absent == "observe":
        return Outcome(resource, State.ABSENT, Did.LEFT_ALONE, why="it is declared `when_absent=\"observe\"`")
    if not ground.mutable:
        return Outcome(
            resource,
            State.ABSENT,
            Did.LEFT_ALONE,
            why=f"the {ground.config.name} environment is not mutable",
        )
    if dry_run:
        return Outcome(resource, State.ABSENT, Did.CREATED, changes=declared_values(resource), why="dry run")

    try:
        record = ground.adapter_for(resource).create(resource)
    except Unreachable as exc:
        return Outcome(resource, State.UNREACHABLE, Did.LEFT_ALONE, why=str(exc))
    return Outcome(resource, State.PRESENT, Did.CREATED, record=record, changes=declared_values(resource))


def _apply(ground: Ground, resource: Any, found: Record, changes: Record) -> Record:
    try:
        return ground.adapter_for(resource).update(resource, found, changes)
    except Unreachable:
        raise
    except Exception as exc:
        raise ProvisionError(
            f"{name_of(resource) or declaration_of(resource).kind}: updating "
            f"{', '.join(sorted(changes))} failed: {type(exc).__name__}: {exc}"
        ) from exc


def provision(ground: Ground, resources: list[Any], *, dry_run: bool = False) -> list[Outcome]:
    """Make each of these, and everything each of them needs, parents first.

    The order comes off the graph, so nothing here says "owners before lists". A resource reached
    twice is provisioned once.
    """
    return [ensure(ground, node, dry_run=dry_run) for node in graph.order(resources)]


def status(ground: Ground, resources: list[Any]) -> list[Outcome]:
    """Where each of these stands, changing nothing.

    `atf status` never gates. Absence is reported as information, because naming a resource in a
    scenario is precisely what makes ATF create it.
    """
    out: list[Outcome] = []
    for node in resources:
        state, found = ground.find(node)
        if state is State.UNREACHABLE:
            out.append(Outcome(node, state, Did.LEFT_ALONE, why=f"the {declaration_of(node).system} system"))
        elif state is State.PRESENT and found is not None:
            changes = diff(node, found)
            out.append(
                Outcome(node, state, Did.UPDATED if changes else Did.UNCHANGED, record=found, changes=changes)
            )
        else:
            out.append(Outcome(node, State.ABSENT, _would(ground, node)))
    return out


def _would(ground: Ground, resource: Any) -> Did:
    """What `atf make` would do about an absent resource, without doing it."""
    declaration = declaration_of(resource)
    if declaration.when_absent in ("require", "observe") or not ground.mutable:
        return Did.LEFT_ALONE
    return Did.CREATED


# --- The two optional methods ----------------------------------------------------------------------


def act(ground: Ground, resource: Any, action: str) -> Any:
    """Run one of the resource's declared verbs — `When I complete the task "laundry"`.

    A system without `act` can still be arranged and claimed about; it has no verbs of its own, and
    saying so here is better than a missing-attribute error inside a step.
    """
    declaration = declaration_of(resource)
    if action not in declaration.actions:
        known = ", ".join(sorted(declaration.actions)) or "none"
        raise ProvisionError(f"{declaration.kind} has no action {action!r} (declared: {known})")
    if not ground.can(resource, "act"):
        raise ProvisionError(
            f"the {declaration.system} system cannot act — its adapter implements no `act`, "
            f"so {declaration.kind}'s `actions=` has nothing to run it"
        )
    state, found = ground.find(resource)
    if state is not State.PRESENT or found is None:
        raise ProvisionError(f"{name_of(resource) or declaration.kind} is {state}, so nothing can act on it")
    return ground.adapter_for(resource).act(resource, found, declaration.actions[action])


def browse(ground: Ground, resource: Any) -> list[Record]:
    """Every record of this resource's kind — `Then the environment has 2 todo_list`.

    A system without `browse` can answer about a resource you named and nothing about the set of
    them, which is a fact about the adapter and is reported as one.
    """
    declaration = declaration_of(resource)
    if not ground.can(resource, "browse"):
        raise ProvisionError(
            f"the {declaration.system} system cannot be listed — its adapter implements no `browse`"
        )
    try:
        return list(ground.adapter_for(resource).browse(resource))
    except Unreachable:
        raise


# --- Teardown -------------------------------------------------------------------------------------


def teardown(ground: Ground, resources: list[Any]) -> list[Outcome]:
    """Remove these, **always in reverse lineage order**, so a list goes before its owner.

    It runs after a failure too. A `persistent` resource is never passed here: outliving the process
    is what makes re-runs cheap and recognition worth having.
    """
    out: list[Outcome] = []
    for node in graph.teardown_order(resources):
        if declaration_of(node).scope == "persistent":
            continue
        state, found = ground.find(node)
        if state is not State.PRESENT or found is None:
            out.append(Outcome(node, state, Did.LEFT_ALONE, why="it was not there"))
            continue
        try:
            ground.adapter_for(node).delete(node, found)
        except Unreachable as exc:
            out.append(Outcome(node, State.UNREACHABLE, Did.LEFT_ALONE, why=str(exc)))
            continue
        out.append(Outcome(node, State.ABSENT, Did.UPDATED, why="removed"))
    return out


def scoped(resources: list[Any], scope: str) -> list[Any]:
    """Just the resources of one scope, for whoever owns that scope's end."""
    return [node for node in resources if declaration_of(node).scope == scope]


def ephemeral(resources: list[Any]) -> list[Any]:
    """Everything ATF will take away again — anything not `persistent`."""
    return [node for node in resources if declaration_of(node).scope != "persistent"]


def unnamed(resource: Any) -> bool:
    """Whether this resource came from a factory rather than from a variable in a module."""
    return instance_of(resource).from_factory
