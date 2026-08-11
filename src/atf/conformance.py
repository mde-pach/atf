"""The contract an adapter answers to, run against a real environment as a series of claims."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from typing_extensions import override

from . import reconcile
from .declare import Unreachable, declaration_of, instance_of, values_of
from .environment import Ground, view
from .runtime import varied
from .spi import State

#: What a recognition value is marked with, so nothing this writes can be mistaken for real data.
MARK = "atf-verify"


@dataclass(frozen=True)
class Finding:
    """One thing the contract asks of an adapter, and whether it held."""

    what: str
    held: bool
    why: str = ""

    @override
    def __str__(self) -> str:
        return f"{'ok  ' if self.held else 'FAIL'}  {self.what}{'' if self.held else f' — {self.why}'}"


class Unverifiable(Exception):
    """Raised when the contract cannot be put to this resource at all."""


def _stand_in(resource: Any) -> Any:
    """A copy of a resource recognised by a value nothing else uses.

    Every recognised field is a declared scalar, so each is marked. The copy is never the resource
    a suite named, and what this writes is deleted before it returns.
    """
    declaration = declaration_of(resource)
    if not declaration.unique_by:
        raise Unverifiable(f"{declaration.kind} declares no `unique_by`, so nothing recognises a copy")
    patch: dict[str, str] = {}
    for field in declaration.unique_by:
        value = values_of(resource).get(field)
        if not isinstance(value, str):
            raise Unverifiable(
                f"{declaration.kind} is recognised by {field!r}, which holds {value!r}. "
                f"This runs against a resource recognised by text."
            )
        patch[field] = f"{value}-{MARK}"
    copy = varied(resource, patch)
    instance_of(copy).ephemeral = True
    return copy


def verify(ground: Ground, resource: Any) -> list[Finding]:
    """Put this resource's adapter through the four required methods and report what held.

    Everything is done to a marked copy, and the copy is removed whether the contract held or not.
    """
    declaration = declaration_of(resource)
    if not ground.mutable:
        raise Unverifiable(f"{ground.config.name} is not mutable, and this writes")
    if declaration.when_absent != "make":
        raise Unverifiable(f'{declaration.kind} is declared `when_absent="{declaration.when_absent}"`')

    stand_in = _stand_in(resource)
    adapter = ground.adapter_for(stand_in)
    found: list[Finding] = []

    try:
        found.append(_absent_is_absent(ground, stand_in))
        found.append(_create_returns_the_record(adapter, stand_in))
        found.append(_created_matches_its_declaration(ground, stand_in))
        found += _update_writes(ground, adapter, stand_in)
        gone, removed = _delete_removes(ground, adapter, stand_in)
        found.append(gone)
        found.append(_delete_is_idempotent(adapter, stand_in, removed))
    finally:
        _remove(ground, adapter, stand_in)
    return found


def _absent_is_absent(ground: Ground, resource: Any) -> Finding:
    state, record = ground.find(resource)
    if state is State.UNREACHABLE:
        return Finding("a resource nothing made is absent", False, "the system could not be reached")
    if state is State.ABSENT and record is None:
        return Finding("a resource nothing made is absent", True)
    return Finding(
        "a resource nothing made is absent",
        False,
        f"`find` answered {record!r} for a recognition value nothing has written",
    )


def _create_returns_the_record(adapter: Any, resource: Any) -> Finding:
    try:
        record = adapter.create(view(resource))
    except Unreachable as exc:
        return Finding("`create` answers with the record it wrote", False, str(exc))
    if not isinstance(record, dict) or not record:
        return Finding("`create` answers with the record it wrote", False, f"it answered {record!r}")
    return Finding("`create` answers with the record it wrote", True)


def _created_matches_its_declaration(ground: Ground, resource: Any) -> Finding:
    state, record = ground.find(resource)
    if state is not State.PRESENT or record is None:
        return Finding("what `create` wrote is what `find` reads back", False, f"`find` says {state}")
    changes = reconcile.diff(resource, record)
    if changes:
        return Finding(
            "what `create` wrote is what `find` reads back",
            False,
            f"these differ straight after creating: {', '.join(sorted(changes))}",
        )
    return Finding("what `create` wrote is what `find` reads back", True)


def _writable_field(resource: Any) -> str:
    """A declared scalar that is not part of what recognises the resource."""
    recognised = set(declaration_of(resource).unique_by)
    for field, value in values_of(resource).items():
        if field not in recognised and isinstance(value, str):
            return field
    return ""


def _update_writes(ground: Ground, adapter: Any, resource: Any) -> list[Finding]:
    field = _writable_field(resource)
    if not field:
        return [Finding("`update` writes what it is handed", True, "no field to write; nothing asked")]
    state, record = ground.find(resource)
    if state is not State.PRESENT or record is None:
        return [Finding("`update` writes what it is handed", False, f"`find` says {state}")]
    wanted = f"{values_of(resource).get(field)}-changed"
    try:
        adapter.update(view(resource), record, {field: wanted})
    except Unreachable as exc:
        return [Finding("`update` writes what it is handed", False, str(exc))]
    _, after = ground.find(resource)
    if after is None or str(after.get(field)) != wanted:
        return [
            Finding(
                "`update` writes what it is handed",
                False,
                f"{field} reads {None if after is None else after.get(field)!r} after being set to {wanted!r}",
            )
        ]
    return [Finding("`update` writes what it is handed", True)]


def _delete_removes(ground: Ground, adapter: Any, resource: Any) -> tuple[Finding, Any]:
    """Whether `delete` takes it away, and the record it was handed."""
    _, record = ground.find(resource)
    if record is None:
        return Finding("`delete` takes the resource away", False, "it was already gone"), None
    try:
        adapter.delete(view(resource), record)
    except Unreachable as exc:
        return Finding("`delete` takes the resource away", False, str(exc)), record
    state, _ = ground.find(resource)
    if state is not State.ABSENT:
        return Finding("`delete` takes the resource away", False, f"`find` still says {state}"), record
    return Finding("`delete` takes the resource away", True), record


def _delete_is_idempotent(adapter: Any, resource: Any, record: Any) -> Finding:
    """Deleting the same record twice is what a killed run leaves behind for the next one."""
    what = "`delete` on a record already gone is not an error"
    if record is None:
        return Finding(what, True, "nothing was deleted, so nothing asked")
    try:
        adapter.delete(view(resource), record)
    except Unreachable as exc:
        return Finding(what, False, str(exc))
    except Exception as exc:  # noqa: BLE001 - anything at all here is the finding
        return Finding(what, False, f"{type(exc).__name__}: {exc}")
    return Finding(what, True)


def _remove(ground: Ground, adapter: Any, resource: Any) -> None:
    """Take the marked copy away, whatever the contract said."""
    try:
        _, record = ground.find(resource)
        if record is not None:
            adapter.delete(view(resource), record)
    except Exception:  # noqa: BLE001 - cleaning up is best effort, and the findings are the answer
        return
