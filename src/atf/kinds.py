"""The kind registry: `any uuid`, `set`, `missing`, and whatever a suite registers."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .model import compare

#: The adjective that introduces a registered kind. `set` and `missing` are said without it.
ANY = "any"

Verdict = tuple[bool, str]
#: One argument for an ordinary kind; a second for one that takes a pattern, like `any text like ^AC-`.
Test = Callable[..., Verdict]


class KindError(Exception):
    """Raised when a kind is registered twice, or a scenario says one nobody registered."""


@dataclass(frozen=True)
class Kind:
    """One registered kind, and how it is said."""

    name: str
    test: Test
    takes_argument: bool = False
    #: Whether it is said with `any` in front of it. `set` and `missing` are not.
    bare: bool = False

    @property
    def said(self) -> str:
        return self.name if self.bare else f"{ANY} {self.name}"


REGISTRY: dict[str, Kind] = {}


def kind(name: str, *, takes_argument: bool = False, bare: bool = False) -> Callable[[Test], Test]:
    """Register a kind. Written without `any`, which is how a scenario says it."""

    def decorate(test: Test) -> Test:
        clean = name.strip()
        seen = REGISTRY.get(clean)
        if seen is not None and seen.test is not test:
            raise KindError(f"two kinds are called {clean!r}")
        REGISTRY[clean] = Kind(name=clean, test=test, takes_argument=takes_argument, bare=bare)
        return test

    return decorate


def named(written: str) -> tuple[Kind, str] | None:
    """The kind this text says, with whatever was written after it, or nothing where it says none."""
    text = written.strip()
    bare = REGISTRY.get(text)
    if bare is not None and bare.bare:
        return bare, ""
    head, _, rest = text.partition(" ")
    if head != ANY:
        return None
    rest = rest.strip()
    # Longest first: `any whole number` is one kind, and `any number` is another.
    for name in sorted(REGISTRY, key=len, reverse=True):
        if rest == name:
            return REGISTRY[name], ""
        if rest.startswith(f"{name} "):
            return REGISTRY[name], rest[len(name) + 1 :].strip()
    name, _, argument = rest.partition(" ")
    known = REGISTRY.get(name)
    if known is None:
        offered = ", ".join(sorted(one.said for one in REGISTRY.values())) or "none"
        raise KindError(
            f"no kind is registered as {text!r}.\n"
            f"  Registered: {offered}.\n"
            f"  A team registers its own with `@kind(\"iban\")`; ATF ships none that know a domain."
        )
    return known, argument.strip()


def says_a_kind(written: str) -> bool:
    """Whether this text says a kind. Never raises; an unregistered `any …` still says one."""
    try:
        return named(written) is not None
    except KindError:
        return True


def holds(value: Any, written: str, *, present: bool = True) -> Verdict:
    """Whether a value is the kind this text asks for. `present=False` means the field is not there."""
    found = named(written)
    if found is None:
        raise KindError(f"{written!r} does not say a kind")
    one, argument = found

    # Presence is asked of the field, not of its value, so these two are answered before any test
    # ever sees a value that may not exist.
    if one.name == "set":
        return present, "the field is not there"
    if one.name == "missing":
        return not present, "the field is there"
    if not present:
        return False, "the field is not there"
    if one.takes_argument:
        return one.test(value, argument)
    return one.test(value)


def offered() -> list[str]:
    """Every kind a scenario may say here, as it is said. What the editor lists and lint suggests."""
    return sorted(one.said for one in REGISTRY.values())


_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _register_shipped() -> None:
    """The kinds ATF ships. Every one is about structure; none knows a domain."""

    def structural(name: str, description: str, test: Callable[[Any], bool]) -> None:
        kind(name)(lambda value: (test(value), f"{compare.describe(value)} is not {description}"))

    structural("uuid", "a UUID", lambda v: isinstance(v, str) and bool(_UUID.match(v)))
    structural("datetime", "a date and a time", lambda v: compare.marker_matches(v, "#datetime"))
    structural("date", "a date", lambda v: compare.marker_matches(v, "#date"))
    structural("time", "a time of day", lambda v: compare.marker_matches(v, "#time"))
    structural("number", "a number", lambda v: isinstance(v, int | float) and not isinstance(v, bool))
    structural("whole number", "a whole number", lambda v: isinstance(v, int) and not isinstance(v, bool))
    structural("text", "text", lambda v: isinstance(v, str))

    kind("text like", takes_argument=True)(
        lambda value, pattern: (
            isinstance(value, str) and bool(_search(pattern, value)),
            f"{compare.describe(value)} does not match {pattern}",
        )
    )

    # These two are about whether the field is *there*, so `holds` answers them before any value is
    # looked at. Registered so that they are listed with the rest.
    kind("set", bare=True)(lambda value: (True, ""))
    kind("missing", bare=True)(lambda value: (True, ""))


def _search(pattern: str, value: str) -> Any:
    """A pattern that will not compile is not a match, never a crash — the scenario is what is wrong."""
    try:
        return re.search(pattern, value)
    except re.error:
        return None


_register_shipped()
