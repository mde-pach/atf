"""Bringing a resource to what its declaration says, and taking it away again."""

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
class Reconciliation:
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


def acted_fields(resource: Any) -> set[str]:
    """Fields a declared action writes, which reconciliation must not undo.

    A field named by both the shape and an action is declared for its *initial* value, and is not
    held to it afterwards.
    """
    return {field for action in declaration_of(resource).actions.values() for field in action.values}


def declared_values(resource: Any) -> Record:
    """The fields ATF writes when it creates: everything declared that is not another resource.

    A field holding a parent is left out; the adapter resolves it. `comparable_values` is what a
    diff is taken over.
    """
    return {name: value for name, value in values_of(resource).items() if not is_resource(value)}


def comparable_values(resource: Any) -> Record:
    """What the diff is taken over: the declared scalars, minus what an action is free to change.

    A field a scenario varied is always compared, even where an action writes it.
    """
    loose = acted_fields(resource) - instance_of(resource).varied
    return {name: value for name, value in declared_values(resource).items() if name not in loose}


def parent_key(resource: Any, field_name: str) -> str:
    """What a record calls the parent held in this field.

    `owner` is written as `owner_id`, unless the adapter names a `parent_suffix` option.
    """
    suffix = declaration_of(resource).options.get("parent_suffix", "_id")
    return f"{field_name}{suffix}"


def parent_identity(parent: Any, record: Record) -> Any:
    """What a parent's record is known by, so a child can be checked against it."""
    return record.get(str(declaration_of(parent).options.get("id_field", "id")))


def parent_changes(resource: Any, found: Record) -> Record:
    """Parents this record no longer points at.

    Checked only where the record carries the key. An adapter that spells lineage some other way
    contributes nothing here.
    """
    out: Record = {}
    for field_name, value in values_of(resource).items():
        if not is_resource(value):
            continue
        key = parent_key(resource, field_name)
        if key not in found:
            continue
        wanted = instance_of(value).identity
        if wanted is None:
            continue
        if not same_value(found.get(key), wanted):
            out[key] = wanted
    return out


def same_value(found: Any, declared: Any) -> bool:
    """Whether a record already satisfies a declared value.

    A field declared as nothing and found as nothing agrees with its declaration. `compare.matches`
    answers a claim's question, where a record holding nothing has not returned the right record.
    """
    if declared is None:
        return found is None
    return compare.matches(found, declared)


def diff(resource: Any, found: Record) -> Record:
    """The declared fields the found record does not already satisfy."""
    changed = {
        name: value
        for name, value in comparable_values(resource).items()
        if not same_value(found.get(name, None), value)
    }
    return {**changed, **parent_changes(resource, found)}


def ensure(ground: Ground, resource: Any, *, dry_run: bool = False) -> Reconciliation:
    """Bring one resource to what its declaration says, and report what that took.

    Only this resource. Everything it needs is [closure](graph.py)'s job, and `provision` walks that.
    """
    declaration = declaration_of(resource)
    state, found = ground.find(resource)

    if state is State.UNREACHABLE:
        why = f"the {declaration.system} system could not be reached"
        return Reconciliation(resource, state, Did.LEFT_ALONE, why=why)

    if state is State.PRESENT and found is not None:
        _remember_identity(resource, found)
        changes = diff(resource, found)
        if not changes:
            return Reconciliation(resource, State.PRESENT, Did.UNCHANGED, record=found)
        if not ground.mutable:
            return Reconciliation(
                resource,
                State.PRESENT,
                Did.LEFT_ALONE,
                record=found,
                changes=changes,
                why=f"the {ground.config.name} environment is not mutable",
            )
        if declaration.when_absent == "observe":
            return Reconciliation(resource, State.PRESENT, Did.LEFT_ALONE, record=found, changes=changes, why="observe")
        if dry_run:
            return Reconciliation(resource, State.PRESENT, Did.UPDATED, record=found, changes=changes, why="dry run")
        return Reconciliation(
            resource,
            State.PRESENT,
            Did.UPDATED,
            record=_apply(ground, resource, found, changes),
            changes=changes,
        )

    # Absent from here down.
    if declaration.when_absent == "require":
        return Reconciliation(
            resource,
            State.ABSENT,
            Did.LEFT_ALONE,
            why=f"it is declared `when_absent=\"require\"`, and {ground.config.name} does not have it",
        )
    if declaration.when_absent == "observe":
        return Reconciliation(resource, State.ABSENT, Did.LEFT_ALONE, why="it is declared `when_absent=\"observe\"`")
    if not ground.mutable:
        return Reconciliation(
            resource,
            State.ABSENT,
            Did.LEFT_ALONE,
            why=f"the {ground.config.name} environment is not mutable",
        )
    if dry_run:
        return Reconciliation(resource, State.ABSENT, Did.CREATED, changes=declared_values(resource), why="dry run")

    try:
        record = ground.adapter_for(resource).create(resource)
    except Unreachable as exc:
        return Reconciliation(resource, State.UNREACHABLE, Did.LEFT_ALONE, why=str(exc))
    _remember_identity(resource, record)
    return Reconciliation(resource, State.PRESENT, Did.CREATED, record=record, changes=declared_values(resource))


def _remember_identity(resource: Any, record: Record) -> None:
    """Keep what this resource was found as, so its children can be checked against it.

    `provision` walks a closure parents-first, so a child's parents have each been through here.
    Held for the process only.
    """
    instance_of(resource).identity = parent_identity(resource, record)


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


def provision(ground: Ground, resources: list[Any], *, dry_run: bool = False) -> list[Reconciliation]:
    """Make each of these, and everything each of them needs, parents first.

    The order comes off the graph, so nothing here says "owners before lists". A resource reached
    twice is provisioned once.
    """
    return [ensure(ground, node, dry_run=dry_run) for node in graph.order(resources)]


def status(ground: Ground, resources: list[Any]) -> list[Reconciliation]:
    """Where each of these stands, changing nothing.

    `atf status` never gates: absence is information, and the exit code is `0` or `2`.
    """
    _learn_parents(ground, resources)
    out: list[Reconciliation] = []
    asked = ground.find_all(resources)
    for node in resources:
        state, found = asked[id(node)]
        if state is State.UNREACHABLE:
            out.append(Reconciliation(node, state, Did.LEFT_ALONE, why=f"the {declaration_of(node).system} system"))
        elif state is State.PRESENT and found is not None:
            changes = diff(node, found)
            out.append(
                Reconciliation(node, state, Did.UPDATED if changes else Did.UNCHANGED, record=found, changes=changes)
            )
        else:
            out.append(Reconciliation(node, State.ABSENT, _would(ground, node)))
    return out


def _learn_parents(ground: Ground, resources: list[Any]) -> None:
    """Find each parent, so a child can be compared against the one it should point at.

    The closure minus what was requested: asked about, and not reported on.
    """
    requested = [id(node) for node in resources]
    parents = [node for node in graph.order(resources) if id(node) not in requested]
    asked = ground.find_all(parents)
    for node in parents:
        state, found = asked[id(node)]
        if state is State.PRESENT and found is not None:
            _remember_identity(node, found)


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


def restore(ground: Ground, resources: list[Any], undone: list[str] | None = None) -> list[Reconciliation]:
    """Put back what an action changed, so a declaration holds after a test as well as before it.

    Only the fields a declared action writes, and only on resources ATF will not take away. A
    resource that is torn down needs nothing put back, a field no action names was never loosed, and
    a system named in `undone` put everything back itself.
    """
    rolled_back = set(undone or ())
    out: list[Reconciliation] = []
    for node in resources:
        if scope_of(node) != "persistent" or not ground.mutable:
            continue
        if declaration_of(node).system in rolled_back:
            continue
        loosed = acted_fields(node)
        if not loosed:
            continue
        state, found = ground.find(node)
        if state is not State.PRESENT or found is None:
            continue
        changes = {
            name: value
            for name, value in declared_values(node).items()
            if name in loosed and not same_value(found.get(name, None), value)
        }
        if not changes:
            continue
        try:
            written = _apply(ground, node, found, changes)
        except (ProvisionError, Unreachable) as exc:
            out.append(Reconciliation(node, state, Did.LEFT_ALONE, record=found, changes=changes, why=str(exc)))
            continue
        out.append(
            Reconciliation(node, State.PRESENT, Did.UPDATED, record=written, changes=changes, why="restored")
        )
    return out


# --- Teardown -------------------------------------------------------------------------------------


def teardown(ground: Ground, resources: list[Any], undone: list[str] | None = None) -> list[Reconciliation]:
    """Remove these, **always in reverse lineage order**, so a list goes before its owner.

    It runs after a failure too. A `persistent` resource is never passed here: outliving the process
    is what makes re-runs cheap and recognition worth having. A system named in `undone` rolled the
    whole test back, and has nothing left to delete.
    """
    rolled_back = set(undone or ())
    out: list[Reconciliation] = []
    for node in graph.teardown_order(resources):
        if scope_of(node) == "persistent" or declaration_of(node).system in rolled_back:
            continue
        state, found = ground.find(node)
        if state is not State.PRESENT or found is None:
            out.append(Reconciliation(node, state, Did.LEFT_ALONE, why="it was not there"))
            continue
        try:
            ground.adapter_for(node).delete(node, found)
        except Unreachable as exc:
            out.append(Reconciliation(node, State.UNREACHABLE, Did.LEFT_ALONE, why=str(exc)))
            continue
        out.append(Reconciliation(node, State.ABSENT, Did.UPDATED, why="removed"))
    return out


def scope_of(resource: Any) -> str:
    """How long this resource lives. A copy varied on a recognised field lives for the test."""
    return "function" if instance_of(resource).ephemeral else declaration_of(resource).scope


def scoped(resources: list[Any], scope: str) -> list[Any]:
    """Just the resources of one scope, for whoever owns that scope's end."""
    return [node for node in resources if scope_of(node) == scope]


def ephemeral(resources: list[Any]) -> list[Any]:
    """Everything ATF will take away again — anything not `persistent`."""
    return [node for node in resources if scope_of(node) != "persistent"]


def unnamed(resource: Any) -> bool:
    """Whether a factory built this resource. `False` for one a module names."""
    return instance_of(resource).from_factory
