"""The sentences ATF ships, registered through the same registry a suite uses."""

from __future__ import annotations

from typing import Any

from . import claims
from .declare import declaration_of
from .runtime import Scope
from .steps import given, then, when

# --- Arrange ---------------------------------------------------------------------------------------


@given('the {kind} "{name}"')
def _arrange_named(kind: str, name: str, atf: Scope) -> Any:
    """`Given the todo_list "groceries"` — that resource, and everything its lineage needs."""
    return atf.arrange(kind, name)


@given("a {kind}")
def _arrange_any(kind: str, atf: Scope) -> Any:
    """`Given an owner` — any one; the factory builds it when the scenario named none."""
    return atf.arrange_any(kind)


@given('the {kind} "{name}" but "{field}" is "{value}"')
def _arrange_varied(kind: str, name: str, field: str, value: str, atf: Scope) -> Any:
    """The first sentence of a variation: the resource, and one field changed."""
    return atf.arrange(kind, name, patch={field: value})


@given('"{field}" is "{value}"')
def _arrange_varied_more(field: str, value: str, atf: Scope) -> Any:
    """A continuation: one more field of whatever the previous `Given` named."""
    return atf.vary(field, value)


# --- Act -------------------------------------------------------------------------------------------


@when('I run "{command}"', target="result")
def _run(command: str, shell: Any) -> Any:
    """`When I run "todo show primary@example.com"`."""
    return shell(command)


@when('I run "{command}" as "{slot}"')
def _run_as(command: str, slot: str, shell: Any, atf: Scope) -> Any:
    """The same, kept under a name, for a test that does two things."""
    return atf.remember(slot, shell(command))


@when('I {action} the {kind} "{name}"')
def _act(action: str, kind: str, name: str, atf: Scope) -> Any:
    """`When I complete the task "laundry"` — one of the resource's declared verbs."""
    return atf.act(kind, name, action)


@when("I list every {kind}")
def _browse(kind: str, atf: Scope) -> Any:
    """`When I list every todo_list` — everything of that kind the environment holds."""
    return atf.remember("result", atf.browse(kind))


# --- Assert ----------------------------------------------------------------------------------------


@then('the {kind} "{name}" exists')
def _exists(kind: str, name: str, atf: Scope) -> None:
    claims.exists(atf.look_up(kind, name), f'the {kind} "{name}"')


@then('the {kind} "{name}" is gone')
def _is_gone(kind: str, name: str, atf: Scope) -> None:
    claims.is_gone(atf.look_up(kind, name), f'the {kind} "{name}"')


@then('the {kind} "{name}" field "{field}" is {value}')
def _field_is(kind: str, name: str, field: str, value: str, atf: Scope) -> None:
    """`is "groceries"` compares a value; `is #uuid` asks for a kind."""
    record = atf.look_up(kind, name)
    claims.exists(record, f'the {kind} "{name}"')
    claims.field_is(record, field, _unquote(value), subject=f'the {kind} "{name}"')


@then('the {kind} "{name}" field "{field}" contains "{value}"')
def _field_contains(kind: str, name: str, field: str, value: str, atf: Scope) -> None:
    record = atf.look_up(kind, name)
    claims.exists(record, f'the {kind} "{name}"')
    claims.field_contains(record, field, value, subject=f'the {kind} "{name}"')


@then('the {slot} field "{field}" is {value}')
def _slot_field_is(slot: str, field: str, value: str, atf: Scope) -> None:
    """`Then the result field "exit_code" is "0"` — a claim about what an action produced."""
    claims.field_is(atf.recall(slot), field, _unquote(value), subject=f"the {slot}")


@then('the {slot} field "{field}" contains "{value}"')
def _slot_field_contains(slot: str, field: str, value: str, atf: Scope) -> None:
    claims.field_contains(atf.recall(slot), field, value, subject=f"the {slot}")


@then("the environment has {count:d} {kind}")
def _counted(count: str, kind: str, atf: Scope) -> None:
    claims.counted(atf.browse(kind), int(count), kind)


# --- Using an interface ------------------------------------------------------------------------
#
# Every one of these asks by **role and accessible name**. That is what a screen reader announces,
# and it is the thing worth claiming on — a CSS class is not.


@then('the {role} "{name}" is showing')
def _showing(role: str, name: str, atf: Scope) -> None:
    held = _page(atf).get_by_role(role, name=name).count() > 0
    claims.held((held, _instead(atf, role)), subject=f'the {role} "{name}"')


@then('the {role} "{name}" is not showing')
def _not_showing(role: str, name: str, atf: Scope) -> None:
    gone = _page(atf).get_by_role(role, name=name).count() == 0
    claims.held((gone, "it is on the page"), subject=f'the {role} "{name}"')


@then('the {role} "{name}" reads "{text}"')
def _reads(role: str, name: str, text: str, atf: Scope) -> None:
    control = _found(atf, role, name)
    said = (control.first.text_content() or "").strip()
    claims.held((said == text, f"it reads {said!r}"), subject=f'the {role} "{name}"')


@then('the {role} "{name}" is disabled')
def _disabled(role: str, name: str, atf: Scope) -> None:
    control = _found(atf, role, name)
    claims.held((not control.first.is_enabled(), "it is enabled"), subject=f'the {role} "{name}"')


@then('the {role} "{name}" is enabled')
def _enabled(role: str, name: str, atf: Scope) -> None:
    control = _found(atf, role, name)
    claims.held((control.first.is_enabled(), "it is disabled"), subject=f'the {role} "{name}"')


@then('the words "{words}" are showing')
def _words_showing(words: str, atf: Scope) -> None:
    held = _page(atf).get_by_text(words, exact=False).count() > 0
    claims.held((held, f'"{words}" is not on the page'), subject="")


def _found(atf: Scope, role: str, name: str) -> Any:
    """The control, or a failure naming what was there instead."""
    control = _page(atf).get_by_role(role, name=name)
    if control.count() == 0:
        claims.fail(f'no {role} "{name}" on the page\n    {_instead(atf, role)}')
    return control


def _instead(atf: Scope, role: str) -> str:
    """What is on the page with that role, which is what a wrong name most wants to know."""
    named = [
        (one.get_attribute("aria-label") or (one.text_content() or "").strip())
        for one in _page(atf).get_by_role(role).all()
    ]
    if not named:
        return f"there is no {role} on the page at all"
    return f"{role}s on the page: " + ", ".join(f'"{one}"' for one in named if one)


@when('I click the {role} "{name}"')
def _click(role: str, name: str, atf: Scope) -> None:
    _page(atf).get_by_role(role, name=name).first.click()


@when('I type "{text}" into the {role} "{name}"')
def _type_into(text: str, role: str, name: str, atf: Scope) -> None:
    _page(atf).get_by_role(role, name=name).first.fill(text)


def _page(atf: Scope) -> Any:
    """The one page this scenario is looking at.

    A scenario arranges exactly one `browser` resource, so there is nothing to disambiguate here —
    two of a kind in scope was already refused at collection.
    """
    looking = [node for node in atf.arranged if declaration_of(node).system == "browser"]
    if not looking:
        claims.fail("this sentence is about a page, and the scenario arranged none")
    return atf.ground.adapters["browser"].page(looking[-1])


def _unquote(written: str) -> str:
    """`"groceries"` is a value and `#uuid` is a kind, and the quotes are what say which."""
    text = written.strip()
    return text[1:-1] if len(text) >= 2 and text[0] == '"' and text[-1] == '"' else text

