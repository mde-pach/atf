"""Named sources of values a catalog body or a step can interpolate.

`${...}` used to resolve exactly two things, both written into the resolver: a node reference and
`now+Nd HH:MM`. Everything that is not a node reference is now a call to a *registered* provider,
so a project can plug in a generator the way it plugs in an adapter.

    ${now+1d 09:00}        a timestamp relative to now
    ${uuid}                a fresh identifier
    ${env:BASE_EMAIL}      a variable from the environment
    ${fake:email}          whatever a project registered under `fake`

**Fresh by default.** Stability is not the point of a generated value — if it must stay put you can
type it once. Randomness is incoherent in exactly one place, a natural key ATF has to look up
again, and the catalog refuses that combination rather than seeding around it: see
`catalog._check_generated_keys`.

**One evaluation per scenario, per expression.** Without that rule a provider is useless in the
place it is most wanted — `When I rename it to "${fake:company}"` followed by an assertion on the
same expression would compare two different companies. Identical expressions inside one scenario
therefore give the same value, and a discriminator distinguishes two that should differ:
`${fake:company}` and `${fake:company#new}`.
"""

from __future__ import annotations

import os
import re
import uuid as _uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

# `<name>` optionally followed by an argument. `:` separates them; anything else is passed through
# whole, which is what keeps `now+1d 09:00` reading exactly as it always did.
CALL_RE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::(?P<argument>.*)|(?P<trailing>.*))$", re.DOTALL)

# Everything after `#` distinguishes two calls that should not share a value. It is not passed on.
DISCRIMINATOR = "#"

_NOW_RE = re.compile(r"^\s*([+-])\s*(\d+)d\s+(\d{1,2}):(\d{2})$")


class Provider(Protocol):
    """A named source of values. One method, because that is all a value needs.

    `keyable` answers the one question the catalog has to ask of a provider: may this be used in a
    natural key? Only the provider knows. A generator of fresh values must say no, or every run
    creates another record; a source that answers from something outside itself — the clock, the
    environment — can say yes.
    """

    keyable: bool

    def value(self, argument: str) -> Any: ...


class UnknownProvider(LookupError):
    """A `${...}` naming no registered provider."""


ProviderFactory = Callable[[dict[str, Any]], Provider]

_REGISTRY: dict[str, ProviderFactory] = {}

# What the manifest configures each one with, and the instances built from that. A provider is
# built once and kept: it may hold a connection, a seeded generator or a counter, and rebuilding it
# per value would quietly reset all three.
_SETTINGS: dict[str, dict[str, Any]] = {}
_LIVE: dict[str, Provider] = {}


def register(name: str, factory: ProviderFactory) -> None:
    _REGISTRY[name] = factory
    _LIVE.pop(name, None)


def unregister(name: str) -> None:
    _REGISTRY.pop(name, None)
    _LIVE.pop(name, None)


def registered() -> set[str]:
    return set(_REGISTRY)


def configure(settings: dict[str, dict[str, Any]] | None = None) -> None:
    """Point every provider at one environment's settings, from `environments.<env>.providers`.

    Called once when a suite boots. Everything already built is dropped, because a provider
    configured for the last environment has no business answering for this one.
    """
    _SETTINGS.clear()
    _SETTINGS.update(settings or {})
    _LIVE.clear()


def build(name: str, settings: dict[str, Any] | None = None) -> Provider:
    """A new provider, configured as asked. `instance` is what resolution uses."""
    try:
        factory = _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "none"
        raise UnknownProvider(f"no provider registered as {name!r} (registered: {known})") from None
    return factory(dict(settings if settings is not None else _SETTINGS.get(name, {})))


def keyable(name: str) -> bool:
    """Whether values from this provider may appear in a natural key.

    An unregistered name is *not* refused here: resolution will fail with a message naming it, and
    two errors for one mistake is one too many.
    """
    factory = _REGISTRY.get(name)
    return True if factory is None else bool(getattr(factory, "keyable", False))


def instance(name: str) -> Provider:
    """The live provider under this name, built on first use and kept afterwards."""
    if name not in _LIVE:
        _LIVE[name] = build(name)
    return _LIVE[name]


def split(expression: str) -> tuple[str, str]:
    """`"fake:email"` -> `("fake", "email")`; `"now+1d 09:00"` -> `("now", "+1d 09:00")`.

    A `#discriminator` is stripped here: it exists only to tell two otherwise identical calls apart
    so they do not share a value, and the provider itself must never see it.
    """
    head, _, _ = expression.partition(DISCRIMINATOR)
    match = CALL_RE.match(head.strip())
    if match is None:
        return "", ""
    argument = match.group("argument")
    return match.group("name"), (argument if argument is not None else match.group("trailing") or "")


# ---- the providers ATF ships ------------------------------------------------


class Now:
    """`${now+1d 09:00}` — a moment relative to this one, as the backend spells it.

    Keyable, deliberately. A resource keyed on its own due date gets one record per day and that
    is what someone writing `${now+1d 09:00}` into a key is asking for — unlike a random value,
    which produces a new record every single run and is never what anyone meant.
    """

    keyable = True

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        # Pinned per environment when a suite needs a fixed clock; otherwise the real one.
        at = (settings or {}).get("at")
        self.at: datetime | None = at if isinstance(at, datetime) else None

    def value(self, argument: str) -> Any:
        match = _NOW_RE.match(argument)
        if match is None:
            raise ValueError(f"`now{argument}`: expected `now+1d 09:00` or `now-2d 18:30`")
        sign, days, hour, minute = match.groups()
        offset = timedelta(days=int(days) * (1 if sign == "+" else -1))
        moment = (self.at or datetime.now(UTC)) + offset
        moment = moment.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
        return moment.isoformat().replace("+00:00", "Z")


class Uuid:
    """`${uuid}` — a fresh identifier, or `${uuid:hex}` without the dashes."""

    keyable = False

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        pass

    def value(self, argument: str) -> Any:
        made = _uuid.uuid4()
        return made.hex if argument.strip() == "hex" else str(made)


class Env:
    """`${env:NAME}` — a variable from the process environment, refused when it is not set.

    A missing one is an error rather than an empty string: a resource silently created with a blank
    field is a resource that looks fine and is not.
    """

    keyable = True  # fixed for the life of the process, and usually for far longer

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        pass

    def value(self, argument: str) -> Any:
        name = argument.strip()
        if name not in os.environ:
            raise ValueError(f"`env:{name}`: {name} is not set in this process")
        return os.environ[name]


class Faker:
    """`${fake:email}`, `${fake:company}` — any method the Faker library offers.

    Registered whether or not Faker is installed, so the catalog can still tell that a value from
    it has no business in a natural key. Installing it is what makes one resolve:

        uv sync --group fake

    ATF itself depends on nothing that generates data — a framework should not decide what a
    project's test data looks like.
    """

    keyable = False

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        try:
            from faker import Faker as _Faker
        except ImportError:
            raise ValueError(
                "`fake` needs Faker installed — `uv sync --group fake`, or add it to your project"
            ) from None

        options = dict(settings or {})
        locale = options.pop("locale", None)
        self.faker = _Faker(locale) if locale else _Faker()
        # A seed makes a whole *run* reproducible, which is a different thing from making one value
        # stand still. Off unless a suite asks for it.
        seed = options.pop("seed", None)
        if seed is not None:
            self.faker.seed_instance(seed)

    def value(self, argument: str) -> Any:
        name = argument.strip()
        if not name:
            raise ValueError("`fake` needs a method — `${fake:email}`, `${fake:company}`")
        method = getattr(self.faker, name, None)
        if not callable(method):
            raise ValueError(f"`fake:{name}`: Faker has no such method")
        return method()


def _register_builtins() -> None:
    register("now", Now)
    register("uuid", Uuid)
    register("env", Env)
    register("fake", Faker)


_register_builtins()

__all__ = [
    "DISCRIMINATOR",
    "configure",
    "instance",
    "keyable",
    "Provider",
    "ProviderFactory",
    "UnknownProvider",
    "build",
    "register",
    "registered",
    "split",
    "unregister",
]
