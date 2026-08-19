"""Bringing a resource to what its declaration says, and taking it away again."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import graph, lives
from .declare import (
    Unreachable,
    declaration_of,
    instance_of,
    is_resource,
    name_of,
    values_of,
)
from .environment import Ground
from .model import compare
from .spi import Did, Payload, State


class ProvisionError(Exception):
    """Raised when a resource cannot be brought to what its declaration says."""


@dataclass(frozen=True)
class Reconciliation:
    """What one pass did to one resource, and what the environment holds now."""

    resource: Any
    state: State
    did: Did
    record: Payload | None = None
    changes: Payload = field(default_factory=dict)
    why: str = ""

    @property
    def name(self) -> str:
        return name_of(self.resource) or declaration_of(self.resource).kind


def declared_values(resource: Any) -> Payload:
    """The fields ATF writes when it creates: everything declared that is not another resource.

    A field holding a parent is left out; the system resolves it. `comparable_values` is what a
    diff is taken over.
    """
    return {name: value for name, value in values_of(resource).items() if not is_resource(value)}


def parent_key(resource: Any, field_name: str) -> str:
    """What a record calls the parent held in this field.

    `owner` is written as `owner_id`, unless the system's own class names a `parent_suffix`.
    """
    suffix = getattr(type(resource), "parent_suffix", "_id")
    return f"{field_name}{suffix}"


def parent_identity(parent: Any, record: Payload) -> Any:
    """What a parent's record is known by, so a child can be checked against it."""
    return record.get(str(getattr(type(parent), "id_field", "id")))


def parent_changes(resource: Any, found: Payload) -> Payload:
    """Parents this record no longer points at.

    Checked only where the record carries the key. A system that spells lineage some other way
    contributes nothing here.
    """
    out: Payload = {}
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


def diff(resource: Any, found: Payload) -> Payload:
    """The declared fields the found record does not already satisfy."""
    changed = {
        name: value
        for name, value in declared_values(resource).items()
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
        if ground.owner_of(resource) == "them":
            return Reconciliation(
                resource,
                State.PRESENT,
                Did.LEFT_ALONE,
                record=found,
                changes=changes,
                why="they own it, so ATF only looks",
            )
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
    if ground.owner_of(resource) == "them":
        return Reconciliation(
            resource,
            State.ABSENT,
            Did.LEFT_ALONE,
            why=f'it is declared `owner="them"`, and {ground.config.name} does not have it',
        )
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
        record = ground.perform(resource, "create")()
    except Unreachable as exc:
        return Reconciliation(resource, State.UNREACHABLE, Did.LEFT_ALONE, why=str(exc))
    _remember_identity(resource, record)
    return Reconciliation(resource, State.PRESENT, Did.CREATED, record=record, changes=declared_values(resource))


def _remember_identity(resource: Any, record: Payload) -> None:
    """Keep what this resource was found as, so its children can be checked against it.

    `provision` walks a closure parents-first, so a child's parents have each been through here.
    Held for the process only.
    """
    instance_of(resource).identity = parent_identity(resource, record)


def _apply(ground: Ground, resource: Any, found: Payload, changes: Payload) -> Payload:
    try:
        return ground.perform(resource, "update")(changes)
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
    """What a run would do about an absent resource, without doing it."""
    if ground.owner_of(resource) == "them" or not ground.mutable:
        return Did.LEFT_ALONE
    return Did.CREATED


# --- The two optional methods ----------------------------------------------------------------------


def change(ground: Ground, resource: Any, changes: Payload) -> Payload:
    """Write fields onto a resource that is already there.

    The act-time twin of a variation: `Given ... but "done" is "true"` says it before the test runs,
    this says it in the middle of one. It goes through `update`, which every adapter answers.
    """
    declaration = declaration_of(resource)
    if not ground.mutable:
        raise ProvisionError(
            f"the {ground.config.name} environment may not be changed, and this sentence changes "
            f"{name_of(resource) or declaration.kind}"
        )
    state, found = ground.find(resource)
    if state is not State.PRESENT or found is None:
        raise ProvisionError(f"{name_of(resource) or declaration.kind} is {state}, so nothing can change it")
    return _apply(ground, resource, found, changes)


def browse(ground: Ground, resource: Any) -> list[Payload]:
    """Every record of this resource's kind — `Then there are 2 todo_lists`.

    A system without `browse` can answer about a resource you named and nothing about the set of
    them, which is a fact about the class and is reported as one.
    """
    declaration = declaration_of(resource)
    if not ground.can(resource, "browse"):
        raise ProvisionError(
            f"the {declaration.system} system cannot be listed — its class implements no `browse`"
        )
    try:
        return list(resource.browse())
    except Unreachable:
        raise


def restore(
    ground: Ground,
    resources: list[Any],
    loosed: dict[int, set[str]] | None = None,
    undone: list[str] | None = None,
) -> list[Reconciliation]:
    """Put back what a test changed, so a declaration holds after it as well as before it.

    `loosed` is the fields each test wrote, by resource identity. Only on resources ATF will not
    take away, and never on a system named in `undone`, which put everything back itself.
    """
    rolled_back = set(undone or ())
    written_by_test = loosed or {}
    out: list[Reconciliation] = []
    for node in resources:
        if lives.of(node) != lives.FOREVER or not ground.mutable:
            continue
        if declaration_of(node).system in rolled_back:
            continue
        touched = written_by_test.get(id(node), set())
        if not touched:
            continue
        state, found = ground.find(node)
        if state is not State.PRESENT or found is None:
            continue
        changes = {
            name: value
            for name, value in declared_values(node).items()
            if name in touched and not same_value(found.get(name, None), value)
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

    It runs after a failure too. Something living `forever` is never passed here: outliving the process
    is what makes re-runs cheap and recognition worth having. A system named in `undone` rolled the
    whole test back, and has nothing left to delete.
    """
    rolled_back = set(undone or ())
    out: list[Reconciliation] = []
    for node in graph.teardown_order(resources):
        if lives.of(node) == lives.FOREVER or declaration_of(node).system in rolled_back:
            continue
        state, found = ground.find(node)
        if state is not State.PRESENT or found is None:
            out.append(Reconciliation(node, state, Did.LEFT_ALONE, why="it was not there"))
            continue
        try:
            ground.perform(node, "delete")()
        except Unreachable as exc:
            out.append(Reconciliation(node, State.UNREACHABLE, Did.LEFT_ALONE, why=str(exc)))
            continue
        out.append(Reconciliation(node, State.ABSENT, Did.UPDATED, why="removed"))
    return out


def living(resources: list[Any], span: str) -> list[Any]:
    """Just the things of one span, for whoever owns that span's end."""
    return [node for node in resources if lives.of(node) == span]


def ephemeral(resources: list[Any]) -> list[Any]:
    """Everything ATF will take away again — anything that does not live `forever`."""
    return [node for node in resources if lives.of(node) != lives.FOREVER]


def unnamed(resource: Any) -> bool:
    """Whether resolution built this thing. `False` for one a module names."""
    return instance_of(resource).built
