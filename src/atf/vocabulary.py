"""The sentences ATF ships: arranging a thing, and claiming about one or about `it`."""

from __future__ import annotations

from typing import Any

from . import claims, literals
from .runtime import Scope
from .steps import READS, WRITES, act, check, given

# --- Arrange ---------------------------------------------------------------------------------------
#
# Three sentences, and they are `needs()` said in prose. `a` resolves everything, `the` names one,
# and `with` gives the resolver an argument — which is all a variation ever was.


@given('the {kind} "{name}"')
def _the_one(kind: str, name: str, atf: Scope) -> Any:
    """`Given the list "groceries"` — that one, and everything its lineage needs."""
    return atf.arrange(kind, name)


@given("a {kind}")
def _any_one(kind: str, atf: Scope) -> Any:
    """`Given a list` — any one; resolution builds it when the scenario named none."""
    return atf.a(kind)


@given('the {kind} "{name}" with {field} {value}', effect=WRITES)
def _the_one_with(kind: str, name: str, field: str, value: str, atf: Scope) -> Any:
    """`Given the list "groceries" with slug "produce"` — that one, bent."""
    return atf.arrange(kind, name, patch={literals.field_name(field): _plain(value)})


@given("a {kind} with {field} {value}", effect=WRITES)
def _any_one_with(kind: str, field: str, value: str, atf: Scope) -> Any:
    """`Given a list with slug "produce"` — give the resolver an argument; it resolves the rest."""
    return atf.a(kind, {literals.field_name(field): _plain(value)})


@given("with {field} {value}", effect=WRITES)
def _and_with(field: str, value: str, atf: Scope) -> Any:
    """One more field of whatever the previous `Given` named."""
    return atf.vary(literals.field_name(field), _plain(value))


@given("without {field}", effect=WRITES)
def _and_without(field: str, atf: Scope) -> Any:
    """`And without a slug` — the field is not there at all."""
    return atf.vary(literals.field_name(_bare(field)), None)


def _bare(field: str) -> str:
    """`a slug` and `the slug` and `slug` are one field. The article is English, not syntax."""
    words = field.strip().split()
    return " ".join(words[1:]) if words and words[0] in ("a", "an", "the") else field


def _plain(written: str) -> Any:
    """A value out of a sentence, for a field a resource is being given."""
    said = literals.read(written)
    if said.says_a_kind:
        raise literals.LiteralError(f"a field is given a value, and {said.text} is a kind")
    return said.value


# --- Claiming about whatever last happened ---------------------------------------------------------
#
# `it` is whatever last happened, and there is no way to name a result. Assert before you act again
# and you never need one; `the previous` covers the scenario that genuinely holds two at once.


@check("its {field} is {value}")
def _its_field_is(field: str, value: str, atf: Scope) -> None:
    """A field of what last happened is this value, or this kind."""
    claims.field_is(atf.it(), literals.field_name(field), value, subject="its")


@check("its {field} is not {value}")
def _its_field_is_not(field: str, value: str, atf: Scope) -> None:
    """That field of what last happened is anything but this."""
    claims.field_is_not(atf.it(), literals.field_name(field), value, subject="its")


@check("its {field} contains {value}")
def _its_field_contains(field: str, value: str, atf: Scope) -> None:
    """That field holds this somewhere inside it."""
    claims.field_contains(atf.it(), literals.field_name(field), value, subject="its")


@check("its {field} does not contain {value}")
def _its_field_does_not_contain(field: str, value: str, atf: Scope) -> None:
    """That field does not hold this anywhere."""
    claims.field_does_not_contain(atf.it(), literals.field_name(field), value, subject="its")


@check("it mentions {value}")
def _it_mentions(value: str, atf: Scope) -> None:
    """`Then it mentions "groceries"` — anywhere in what came back."""
    claims.mentions(atf.it(), value)


@check("it does not mention {value}")
def _it_does_not_mention(value: str, atf: Scope) -> None:
    """This appears nowhere in what came back."""
    claims.does_not_mention(atf.it(), value)


@check("the previous {field} is {value}")
def _previous_field_is(field: str, value: str, atf: Scope) -> None:
    """The rare scenario holding two results at once. One more and it should have been two scenarios."""
    claims.field_is(atf.previous(), literals.field_name(field), value, subject="the previous")


@check("the previous mentions {value}")
def _previous_mentions(value: str, atf: Scope) -> None:
    """This appears somewhere in what happened before `it`."""
    claims.mentions(atf.previous(), value, subject="the previous")


# --- Claiming about a declared thing -----------------------------------------------------------


@check('the {kind} "{name}" exists')
def _exists(kind: str, name: str, atf: Scope) -> None:
    """That thing is there in this environment, asked now."""
    claims.exists(atf.look_up(kind, name), f'the {kind} "{name}"')


@check('the {kind} "{name}" is gone')
def _is_gone(kind: str, name: str, atf: Scope) -> None:
    """That thing is not there any more."""
    claims.is_gone(atf.look_up(kind, name), f'the {kind} "{name}"')


@check('the {kind} "{name}" {field} is {value}')
def _thing_field_is(kind: str, name: str, field: str, value: str, atf: Scope) -> None:
    """A field of that thing, read from the environment now, is this."""
    record = atf.look_up(kind, name)
    claims.exists(record, f'the {kind} "{name}"')
    claims.field_is(record, literals.field_name(field), value, subject=f'the {kind} "{name}"')


@check('the {kind} "{name}" {field} is not {value}')
def _thing_field_is_not(kind: str, name: str, field: str, value: str, atf: Scope) -> None:
    """A field of that thing is anything but this."""
    record = atf.look_up(kind, name)
    claims.exists(record, f'the {kind} "{name}"')
    claims.field_is_not(record, literals.field_name(field), value, subject=f'the {kind} "{name}"')


@check('the {kind} "{name}" {field} contains {value}')
def _thing_field_contains(kind: str, name: str, field: str, value: str, atf: Scope) -> None:
    """A field of that thing holds this somewhere inside it."""
    record = atf.look_up(kind, name)
    claims.exists(record, f'the {kind} "{name}"')
    claims.field_contains(record, literals.field_name(field), value, subject=f'the {kind} "{name}"')


@check('the {kind} "{name}" {field} does not contain {value}')
def _thing_field_does_not_contain(kind: str, name: str, field: str, value: str, atf: Scope) -> None:
    """A field of that thing does not hold this."""
    record = atf.look_up(kind, name)
    claims.exists(record, f'the {kind} "{name}"')
    claims.field_does_not_contain(
        record, literals.field_name(field), value, subject=f'the {kind} "{name}"'
    )


@check("there are {count:d} {kind}")
def _counted(count: str, kind: str, atf: Scope) -> None:
    """This environment holds exactly this many of that kind."""
    claims.counted(atf.browse(_singular(kind)), int(count), kind)


def _singular(kind: str) -> str:
    return kind.removesuffix("s")


# --- Acting on a declared thing ----------------------------------------------------------------
#
# Every system has an `update`, so every system has this word. A domain verb — `When I archive the
# list` — is a phrase standing over it.


@act('the {kind} "{name}" {field} becomes {value}', effect=WRITES)
def _becomes(kind: str, name: str, field: str, value: str, atf: Scope) -> Any:
    """`When the task "laundry" done becomes true`."""
    return atf.change(kind, name, {literals.field_name(field): _plain(value)})


@act("I list every {kind}", effect=READS)
def _browse(kind: str, atf: Scope) -> Any:
    """`When I list every list` — everything of that kind the environment holds."""
    return atf.browse(kind)
