"""The contract every system answers to, and the two sentences `contract.feature` says it in."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from typing_extensions import override

from . import reconcile
from .declare import Unreachable, declaration_of, instance_of, values_of
from .environment import Ground
from .spi import State
from .steps import act, check

#: What a recognition value is marked with, so nothing this writes can be mistaken for real data.
MARK = "atf-verify"


@dataclass(frozen=True)
class Finding:
    """One thing the contract asks of a system, and whether it held."""

    what: str
    held: bool
    why: str = ""

    @override
    def __str__(self) -> str:
        return f"{'ok  ' if self.held else 'FAIL'}  {self.what}{'' if self.held else f' — {self.why}'}"


class Unverifiable(Exception):
    """Raised when the contract cannot be put to this resource at all."""


def _stand_in(resource: Any) -> Any:
    """A copy of a thing recognised by a value nothing else uses.

    What recognises it is the class's own `Key`, so this marks whatever field is named there. The
    copy is never the thing a suite declared, and what this writes is deleted before it returns.
    """
    declaration = declaration_of(resource)
    recognised = declaration.key
    if not recognised:
        raise Unverifiable(f"the {declaration.system} system declares no Key field")
    values = dict(values_of(resource))
    for field in recognised:
        value = values.get(field, getattr(resource, field, None))
        if not isinstance(value, str):
            raise Unverifiable(
                f"{declaration.kind} is recognised by {field!r}, which holds {value!r}. "
                f"The contract runs against a thing recognised by text."
            )
        values[field] = f"{value}-{MARK}"
    copy = type(resource)(**values)
    record = instance_of(copy)
    record.name = instance_of(resource).name
    record.ephemeral = True
    return copy


def verify(ground: Ground, resource: Any) -> list[Finding]:
    """Put this resource's class through the four required methods and report what held.

    Everything is done to a marked copy, and the copy is removed whether the contract held or not.
    """
    declaration = declaration_of(resource)
    if not ground.mutable:
        raise Unverifiable(f"{ground.config.name} is not ATF's to write in, and this writes")
    if ground.owner_of(resource) == "them":
        raise Unverifiable(f'{declaration.kind} is declared `owner="them"`, so ATF never makes one')

    stand_in = _stand_in(resource)
    found: list[Finding] = []

    try:
        found.append(_absent_is_absent(ground, stand_in))
        found.append(_create_returns_the_record(ground, stand_in))
        found.append(_created_matches_its_declaration(ground, stand_in))
        found += _update_writes(ground, stand_in)
        gone, removed = _delete_removes(ground, stand_in)
        found.append(gone)
        found.append(_delete_is_idempotent(ground, stand_in, removed))
    finally:
        _remove(ground, stand_in)
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


def _create_returns_the_record(ground: Ground, resource: Any) -> Finding:
    try:
        record = ground.perform(resource, "create")()
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


def _writable_field(resource: Any, recognised_by: tuple[str, ...]) -> str:
    """A declared scalar that is not part of what recognises the thing."""
    recognised = set(recognised_by)
    for field, value in values_of(resource).items():
        if field not in recognised and isinstance(value, str):
            return field
    return ""


def _update_writes(ground: Ground, resource: Any) -> list[Finding]:
    field = _writable_field(resource, declaration_of(resource).key)
    if not field:
        return [Finding("`update` writes what it is handed", True, "no field to write; nothing asked")]
    state, record = ground.find(resource)
    if state is not State.PRESENT or record is None:
        return [Finding("`update` writes what it is handed", False, f"`find` says {state}")]
    wanted = f"{values_of(resource).get(field)}-changed"
    try:
        ground.perform(resource, "update")({field: wanted})
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


def _delete_removes(ground: Ground, resource: Any) -> tuple[Finding, Any]:
    """Whether `delete` takes it away, and the record it was handed."""
    _, record = ground.find(resource)
    if record is None:
        return Finding("`delete` takes the resource away", False, "it was already gone"), None
    try:
        ground.perform(resource, "delete")()
    except Unreachable as exc:
        return Finding("`delete` takes the resource away", False, str(exc)), record
    state, _ = ground.find(resource)
    if state is not State.ABSENT:
        return Finding("`delete` takes the resource away", False, f"`find` still says {state}"), record
    return Finding("`delete` takes the resource away", True), record


def _delete_is_idempotent(ground: Ground, resource: Any, record: Any) -> Finding:
    """Deleting the same record twice is what a killed run leaves behind for the next one."""
    what = "`delete` on a record already gone is not an error"
    if record is None:
        return Finding(what, True, "nothing was deleted, so nothing asked")
    try:
        ground.perform(resource, "delete")()
    except Unreachable as exc:
        return Finding(what, False, str(exc))
    except Exception as exc:  # noqa: BLE001 - anything at all here is the finding
        return Finding(what, False, f"{type(exc).__name__}: {exc}")
    return Finding(what, True)


def _remove(ground: Ground, resource: Any) -> None:
    """Take the marked copy away, whatever the contract said."""
    try:
        _, record = ground.find(resource)
        if record is not None:
            ground.perform(resource, "delete")()
    except Exception:  # noqa: BLE001 - cleaning up is best effort, and the findings are the answer
        return


# --- The words the contract is written in ------------------------------------------------------


@act("I put every kind ATF may make through the contract")
def _run_the_contract(atf: Any) -> dict[str, Any]:
    """Create, read back, update, delete, delete again — for every kind this environment owns.

    Everything is done to a marked copy of a declared thing, and every copy is removed whether the
    contract held or not.
    """
    ground = atf.ground
    findings: list[dict[str, Any]] = []
    skipped: list[str] = []
    for kind, cls in sorted(ground.suite.kinds.items()):
        example = next((one for one in ground.suite.instances.values() if type(one) is cls), None)
        if example is None:
            skipped.append(f"{kind}: nothing of that kind is declared")
            continue
        try:
            for one in verify(ground, example):
                findings.append(
                    {"kind": kind, "system": declaration_of(cls).system, "what": one.what,
                     "held": one.held, "why": one.why}
                )
        except Unverifiable as exc:
            skipped.append(f"{kind}: {exc}")
    return {
        "findings": findings,
        "skipped": skipped,
        "broken": [one for one in findings if not one["held"]],
    }


@check("every system held it")
def _held(atf: Any) -> tuple[bool, str]:
    """Every finding the contract made held, and it names the ones that did not."""
    result = atf.it() if isinstance(atf.it(), dict) else {}
    broken = result.get("broken", [])
    if not result.get("findings") and not result.get("skipped"):
        return False, "nothing was put through the contract at all"
    said = "\n    ".join(f"{one['kind']} ({one['system']}): {one['what']} — {one['why']}" for one in broken)
    return not broken, f"{len(broken)} did not hold:\n    {said}"
