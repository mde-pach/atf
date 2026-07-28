"""Acting on an interface, in the words a person would use about it.

Every step here names a control by its **role** and its **accessible name** — `the button "Save"`,
`the textbox "Title"` — and by nothing else. There is no selector anywhere in this module and none
in any catalog that uses it, which is the whole point: a selector describes today's markup, and a
role and a name describe the thing.

That makes a UI scenario the same shape as an API one:

```gherkin
Given the page "compose"                      # a resource, like any other
When I type "A list belongs to its owner" into the textbox "Title"
And I click the button "Save"
Then the feature "Lists" contains a scenario "A list belongs to its owner"
```

The `Then` there is not about the interface at all — it is a claim about a file, read through a
different adapter. Which is what *one engine, any system, the same reading surface* has to mean if
it means anything: the browser is how this scenario acts, not what it is about.

These steps are registered for every suite, because they cost nothing to a suite with no browser in
it. Reaching one without a `browser` system configured says so.
"""

from __future__ import annotations

from typing import Any

import pytest
from pytest_bdd import parsers, then, when

from .adapters.browser import BrowserAdapter
from .materializer import Materializer

# What a scenario may say about a control. Role first, because role is what the thing *is* and the
# name is which one — the same order a screen reader announces them in.
CLICK = 'I click the {role:w} "{name}"'
TYPE_INTO = 'I type "{text}" into the {role:w} "{name}"'
CHOOSE = 'I choose the {role:w} "{name}"'
SHOWING = 'the {role:w} "{name}" is showing'
NOT_SHOWING = 'the {role:w} "{name}" is not showing'
READS = 'the {role:w} "{name}" reads "{text}"'

# Prose has no accessible name — ARIA computes one for things you can *do* something to, and a
# paragraph is not one. So the claim about what a page *says* is about the words themselves, which
# is still what a person reads and still not a selector.
DISABLED = 'the {role:w} "{name}" is disabled'
ENABLED = 'the {role:w} "{name}" is enabled'

WORDS = 'the words "{text}" are showing'
NO_WORDS = 'the words "{text}" are not showing'

# How long to wait for something that should not be there. A control that is absent is absent now:
# waiting the full timeout for every negative claim would make a suite of them unusably slow.
GONE_MS = 1000


@when(parsers.parse(CLICK))
def _(request: pytest.FixtureRequest, role: str, name: str) -> None:
    """Click the control with this role and this accessible name."""
    _control(request, role, name).click()


@when(parsers.parse(TYPE_INTO))
def _(request: pytest.FixtureRequest, text: str, role: str, name: str) -> None:
    """Put text into the control with this role and this accessible name."""
    control = _control(request, role, name)
    control.fill("")
    control.type(text)


@when(parsers.parse(CHOOSE))
def _(request: pytest.FixtureRequest, role: str, name: str) -> None:
    """Choose the option with this accessible name — what a listbox or a menu is for."""
    _control(request, role, name).click()


@then(parsers.parse(SHOWING))
def _(request: pytest.FixtureRequest, role: str, name: str) -> None:
    """Require a control with this role and name to become visible.

    Waits, rather than looking once. An interface that swaps a fragment in after a request has
    settled is not broken, it is asynchronous — and a claim that only ever looks at the first
    instant is a claim that fails for a reason the scenario is not about.
    """
    found = _page(request).get_by_role(role, name=name)
    try:
        found.first.wait_for(state="visible")
    except Exception:  # noqa: BLE001 - not arriving is the outcome, and the message says what is there
        pytest.fail(f'no visible {role} called "{name}" arrived on this page.{_instead(request, role)}')


@then(parsers.parse(NOT_SHOWING))
def _(request: pytest.FixtureRequest, role: str, name: str) -> None:
    """Require no visible control with this role and name.

    Not the same as "is not there": a combobox's options exist in the markup the whole time and are
    hidden until it opens, and *hidden* is what a person means.
    """
    page = _page(request)
    found = page.get_by_role(role, name=name)
    try:
        found.first.wait_for(state="visible", timeout=GONE_MS)
    except Exception:  # noqa: BLE001 - not appearing is the outcome this step wants
        return
    pytest.fail(f'the {role} "{name}" is showing, and this scenario says it should not be.')


@then(parsers.parse(READS))
def _(request: pytest.FixtureRequest, role: str, name: str, text: str) -> None:
    """Compare what a control says with what the scenario says it should."""
    actual = (_control(request, role, name).text_content() or "").strip()
    if actual != text.strip():
        pytest.fail(f'the {role} "{name}" reads "{actual}", not "{text}"')


@then(parsers.parse(DISABLED))
def _(request: pytest.FixtureRequest, role: str, name: str) -> None:
    """Require a control to be there and refuse to be used.

    Distinct from not being there at all, and the difference is the point: an interface that hides
    what you may not do teaches nothing, and one that offers it and then refuses is worse. Disabled
    with a reason beside it is the third option, and this is how a scenario says so.
    """
    if not _control(request, role, name).is_disabled():
        pytest.fail(f'the {role} "{name}" can be used, and this scenario says it should not be.')


@then(parsers.parse(ENABLED))
def _(request: pytest.FixtureRequest, role: str, name: str) -> None:
    """Require a control to be there and usable."""
    if _control(request, role, name).is_disabled():
        pytest.fail(f'the {role} "{name}" is disabled, and this scenario says it should not be.')


@then(parsers.parse(WORDS))
def _(request: pytest.FixtureRequest, text: str) -> None:
    """Require these words to become readable somewhere on the page. Waits, for the same reason."""
    try:
        _page(request).get_by_text(text).first.wait_for(state="visible")
    except Exception:  # noqa: BLE001 - not arriving is the outcome this step reports
        pytest.fail(f'the words "{text}" never appeared anywhere a reader can see on this page.')


@then(parsers.parse(NO_WORDS))
def _(request: pytest.FixtureRequest, text: str) -> None:
    """Require these words not to be readable anywhere on the page."""
    found = _page(request).get_by_text(text)
    try:
        found.first.wait_for(state="visible", timeout=GONE_MS)
    except Exception:  # noqa: BLE001 - not appearing is the outcome this step wants
        return
    pytest.fail(f'the words "{text}" are showing, and this scenario says they should not be.')


# ---- reaching the page ------------------------------------------------------


def _control(request: pytest.FixtureRequest, role: str, name: str) -> Any:
    """The one control with this role and this accessible name, or a failure that says what is there."""
    found = _page(request).get_by_role(role, name=name)
    try:
        count = found.count()
    except Exception as exc:  # noqa: BLE001 - an unknown role is a typo, not a crash
        pytest.fail(f'looking for the {role} "{name}" failed: {exc}')
    if count == 0:
        pytest.fail(f'no {role} called "{name}" is on this page.{_instead(request, role)}')
    return found.first


def _instead(request: pytest.FixtureRequest, role: str) -> str:
    """What *is* on the page with that role, so a wrong name is one line to fix rather than a hunt."""
    try:
        names = _page(request).get_by_role(role).all_text_contents()
    except Exception:  # noqa: BLE001 - a hint must never be the reason a scenario fails
        return ""
    shown = ", ".join(sorted({" ".join(text.split()) for text in names if text.strip()})[:8])
    return f" The {role}s here are: {shown}." if shown else f" There are no {role}s on it at all."


def _page(request: pytest.FixtureRequest) -> Any:
    engine: Materializer = request.getfixturevalue("materializer")
    browsers = [one for one in engine.adapters.values() if isinstance(one, BrowserAdapter)]
    if not browsers:
        pytest.fail(
            "this step drives a browser, and this environment configures no `browser` system. "
            "Add one under `environments.<env>.adapters`."
        )
    if len(browsers) > 1:
        pytest.fail("more than one browser is configured here, so ATF cannot tell which page is meant.")
    try:
        return browsers[0].showing()
    except ValueError as exc:
        pytest.fail(str(exc))
