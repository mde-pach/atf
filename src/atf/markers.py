"""The marker registry: `#uuid`, `#int`, and whatever a suite registers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .model import compare

SIGIL = "#"

Verdict = tuple[bool, str]
# One argument for an ordinary marker; a second for one that takes a pattern, like `#regex ^AC-`.
Check = Callable[..., Verdict]


class MarkerError(Exception):
    """Raised when a marker is registered twice, or a scenario says one nobody registered."""


@dataclass(frozen=True)
class Marker:
    """One registered kind, and what it is called without its sigil."""

    name: str
    check: Check
    takes_argument: bool = False

    @property
    def said(self) -> str:
        return f"{SIGIL}{self.name}"


REGISTRY: dict[str, Marker] = {}


def marker(name: str, *, takes_argument: bool = False) -> Callable[[Check], Check]:
    """Register a marker. Written without the `#`, which is how it is said in a scenario."""

    def decorate(check: Check) -> Check:
        clean = name.lstrip(SIGIL)
        seen = REGISTRY.get(clean)
        if seen is not None and seen.check is not check:
            raise MarkerError(f"two markers are called {clean!r}")
        REGISTRY[clean] = Marker(name=clean, check=check, takes_argument=takes_argument)
        return check

    return decorate


def is_marker(written: str) -> bool:
    return written.strip().startswith(SIGIL)


def holds(value: Any, written: str, *, present: bool = True) -> Verdict:
    """Whether a value is the kind a marker asks for. `present=False` means the field is not there."""
    said = written.strip()
    name, _, argument = said.lstrip(SIGIL).partition(" ")
    known = REGISTRY.get(name)
    if known is None:
        offered = ", ".join(sorted(f"{SIGIL}{other}" for other in REGISTRY)) or "none"
        raise MarkerError(f"no marker is registered as {said!r} (registered: {offered})")

    # Presence is asked of the field, not of its value, so these two are answered before the
    # registry's check ever sees a value that may not exist.
    if name == "present":
        return present, "the field is not there"
    if name == "absent":
        return not present, "the field is there"
    if not present:
        return False, "the field is not there"
    if known.takes_argument:
        return known.check(value, argument.strip())
    return known.check(value)


def _register_builtins() -> None:
    """The markers `assert.md` lists as built in. A closed list, so each can be offered in a menu."""

    def kind(name: str, description: str, test: Callable[[Any], bool]) -> None:
        marker(name)(lambda value: (test(value), f"{compare.describe(value)} is not {description}"))

    kind("uuid", "a UUID", lambda v: compare.marker_matches(v, "#uuid"))
    kind("datetime", "a date and a time", lambda v: compare.marker_matches(v, "#datetime"))
    kind("date", "a date", lambda v: compare.marker_matches(v, "#date"))
    kind("int", "a whole number", lambda v: isinstance(v, int) and not isinstance(v, bool))
    kind("str", "text", lambda v: isinstance(v, str))
    kind("bool", "a true/false value", lambda v: isinstance(v, bool))

    # These two are about whether the field is *there*, so `holds` answers them before any value is
    # looked at. Registered so that they are listed with the rest.
    marker("present")(lambda value: (True, ""))
    marker("absent")(lambda value: (True, ""))


_register_builtins()
