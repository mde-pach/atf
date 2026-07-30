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

**A claim does not care which system answers it.** `the heading "Catalog" is showing` is true of the
HTML a server sent or of the page a browser ran, and ATF ships an adapter for each — `html` and
`browser`. Both answer the same three questions ([`Showing`](adapters/__init__.py)), so which one a
suite configures decides what a claim *costs*, never what it says. Most of what there is to claim
about a server-rendered interface needs no browser at all.

**Acting does.** Clicking and typing ask for a browser and say so where there is none, because
reading a response can never do them and pretending otherwise would make a suite quietly weaker on
the machines that have no browser installed.

These steps are registered for every suite, because they cost nothing to a suite with no interface
in it. Reaching one with no system to look at says so.
"""

from __future__ import annotations

from typing import Any

import pytest
from pytest_bdd import parsers, then, when

from ..adapters import Control, can_show
from ..adapters.browser import BrowserAdapter
from ..engine.materializer import Materializer

# What a scenario may say about a control. Role first, because role is what the thing *is* and the
# name is which one — the same order a screen reader announces them in.
CLICK = 'I click the {role:w} "{name}"'
TYPE_INTO = 'I type "{text}" into the {role:w} "{name}"'
CHOOSE = 'I choose the {role:w} "{name}"'
SHOWING = 'the {role:w} "{name}" is showing'
NOT_SHOWING = 'the {role:w} "{name}" is not showing'
READS = 'the {role:w} "{name}" reads "{text}"'

DISABLED = 'the {role:w} "{name}" is disabled'
ENABLED = 'the {role:w} "{name}" is enabled'

# Prose has no accessible name — ARIA computes one for things you can *do* something to, and a
# paragraph is not one. So the claim about what a page *says* is about the words themselves, which
# is still what a person reads and still not a selector.
WORDS = 'the words "{text}" are showing'
NO_WORDS = 'the words "{text}" are not showing'

# How long to wait for something that should not be there. A control that is absent is absent now:
# waiting the full timeout for every negative claim would make a suite of them unusably slow.
GONE_MS = 1000


@when(parsers.parse(CLICK))
def _(request: pytest.FixtureRequest, role: str, name: str) -> None:
    """Click the control with this role and this accessible name."""
    _acting(request, role, name, "click").click()


@when(parsers.parse(TYPE_INTO))
def _(request: pytest.FixtureRequest, text: str, role: str, name: str) -> None:
    """Put text into the control with this role and this accessible name."""
    control = _acting(request, role, name, "type into")
    control.fill("")
    control.type(text)


@when(parsers.parse(CHOOSE))
def _(request: pytest.FixtureRequest, role: str, name: str) -> None:
    """Choose the option with this accessible name — what a listbox or a menu is for."""
    _acting(request, role, name, "choose from").click()


@then(parsers.parse(SHOWING))
def _(request: pytest.FixtureRequest, role: str, name: str) -> None:
    """Require a control with this role and name to be there for a person to see."""
    _require(request, role, name)


@then(parsers.parse(NOT_SHOWING))
def _(request: pytest.FixtureRequest, role: str, name: str) -> None:
    """Require no visible control with this role and name.

    Not the same as "is not there": a combobox's options exist in the markup the whole time and are
    hidden until it opens, and *hidden* is what a person means.
    """
    if _controls(request, role, name, wait=GONE_MS):
        pytest.fail(f'the {role} "{name}" is showing, and this scenario says it should not be.')


@then(parsers.parse(READS))
def _(request: pytest.FixtureRequest, role: str, name: str, text: str) -> None:
    """Compare what a control says with what the scenario says it should."""
    actual = _require(request, role, name).text.strip()
    if actual != text.strip():
        pytest.fail(f'the {role} "{name}" reads "{actual}", not "{text}"')


@then(parsers.parse(DISABLED))
def _(request: pytest.FixtureRequest, role: str, name: str) -> None:
    """Require a control to be there and refuse to be used.

    Distinct from not being there at all, and the difference is the point: an interface that hides
    what you may not do teaches nothing, and one that offers it and then refuses is worse. Disabled
    with a reason beside it is the third option, and this is how a scenario says so.
    """
    if not _require(request, role, name).disabled:
        pytest.fail(f'the {role} "{name}" can be used, and this scenario says it should not be.')


@then(parsers.parse(ENABLED))
def _(request: pytest.FixtureRequest, role: str, name: str) -> None:
    """Require a control to be there and usable."""
    if _require(request, role, name).disabled:
        pytest.fail(f'the {role} "{name}" is disabled, and this scenario says it should not be.')


@then(parsers.parse(WORDS))
def _(request: pytest.FixtureRequest, text: str) -> None:
    """Require these words to be readable somewhere on the page."""
    if not _says(request, text):
        pytest.fail(f'the words "{text}" are nowhere a reader can see them on this page.')


@then(parsers.parse(NO_WORDS))
def _(request: pytest.FixtureRequest, text: str) -> None:
    """Require these words not to be readable anywhere on the page."""
    if _says(request, text, wait=GONE_MS):
        pytest.fail(f'the words "{text}" are showing, and this scenario says they should not be.')


# ---- asking whatever is showing ---------------------------------------------


def _require(request: pytest.FixtureRequest, role: str, name: str) -> Control:
    """The control this step is about, or a failure that says what is there instead."""
    found = _controls(request, role, name)
    if not found:
        pytest.fail(f'no {role} called "{name}" is showing on this page.{_instead(request, role)}')
    return found[0]


def _controls(request: pytest.FixtureRequest, role: str, name: str, *, wait: float = 0.0) -> list[Control]:
    try:
        return _shown(request).controls(role, name, wait=wait)
    except ValueError as exc:
        pytest.fail(str(exc))
    except Exception as exc:  # noqa: BLE001 - an unknown role is a typo, not a crash
        pytest.fail(f'looking for the {role} "{name}" failed: {exc}')


def _says(request: pytest.FixtureRequest, text: str, *, wait: float = 0.0) -> bool:
    try:
        return _shown(request).says(text, wait=wait)
    except ValueError as exc:
        pytest.fail(str(exc))


def _instead(request: pytest.FixtureRequest, role: str) -> str:
    """What *is* on the page with that role, so a wrong name is one line to fix rather than a hunt."""
    try:
        names = [one.name for one in _shown(request).controls(role, wait=GONE_MS)]
    except Exception:  # noqa: BLE001 - a hint must never be the reason a scenario fails
        return ""
    shown = ", ".join(sorted({" ".join(name.split()) for name in names if name.strip()})[:8])
    return f" The {role}s here are: {shown}." if shown else f" There are no {role}s on it at all."


def _shown(request: pytest.FixtureRequest) -> Any:
    """The system this scenario is looking at.

    Which one it is was settled by the `Given` that opened a page: the plugin notes the adapter that
    provisioned it, so a suite configuring both `html` and `browser` never has to say which a claim
    is about — the resource it named already did.
    """
    context = request.getfixturevalue("context")
    if (opened := getattr(context, "_showing", None)) is not None:
        return opened

    engine: Materializer = request.getfixturevalue("materializer")
    lookable = [one for one in engine.adapters.values() if can_show(one)]
    if not lookable:
        pytest.fail(
            "this step reads an interface, and this environment configures no system that can be "
            "looked at. Add `html` — or `browser`, for the claims that need a page to have run — "
            "under `environments.<env>.adapters`."
        )
    if len(lookable) > 1:
        pytest.fail(
            "this environment configures more than one system that can be looked at, and no step "
            'above this one has opened a page. Say which with `Given the <page type> "<name>"`.'
        )
    return lookable[0]


def _acting(request: pytest.FixtureRequest, role: str, name: str, doing: str) -> Any:
    """The one control an acting step is about, on the page that is actually running."""
    found = _live(request, doing).get_by_role(role, name=name)
    try:
        count = found.count()
    except Exception as exc:  # noqa: BLE001 - an unknown role is a typo, not a crash
        pytest.fail(f'looking for the {role} "{name}" failed: {exc}')
    if count == 0:
        pytest.fail(f'no {role} called "{name}" is on this page.{_instead(request, role)}')
    return found.first


def _live(request: pytest.FixtureRequest, doing: str) -> Any:
    """The running page, for the steps that act on one — which is the half a browser is needed for."""
    engine: Materializer = request.getfixturevalue("materializer")
    browsers = [one for one in engine.adapters.values() if isinstance(one, BrowserAdapter)]
    if not browsers:
        pytest.fail(
            f"this step has to {doing} a control, which needs a page that is running — reading the "
            "HTML a server sent can never do it. Add a `browser` system under "
            "`environments.<env>.adapters`."
        )
    if len(browsers) > 1:
        pytest.fail("more than one browser is configured here, so ATF cannot tell which page is meant.")
    try:
        return browsers[0].showing()
    except ValueError as exc:
        pytest.fail(str(exc))
