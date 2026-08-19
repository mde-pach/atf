"""One environment, live: a driver built per system, and what each resource answers for itself."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .declare import (
    _CURRENT_GROUND,
    DRIVERS,
    Resource,
    Unreachable,
    check_shape,
    declaration_of,
    drivers_wanted,
    offers,
)
from .loader import Suite
from .manifest import Environment as EnvironmentConfig
from .spi import Payload, State, check

#: What each write method does, as a message says it.
_DONE = {"create": "made", "update": "changed", "delete": "removed"}


class GroundError(Exception):
    """Raised when an environment cannot be built, or cannot answer for a system it must.

    Named for the band the specification puts an environment in. Not `EnvironmentError`, which is
    a builtin alias of `OSError`.
    """


@dataclass
class Ground:
    """A suite pointed at one environment, with a driver built for each system it uses.

    The name is the band the specification puts an environment in. It holds no state about what has
    been made: presence is asked, never remembered. Every declared resource carries its own
    find/create/update/delete — this holds the machinery each of those reaches for by name.
    """

    suite: Suite
    config: EnvironmentConfig
    #: The machinery each resource works through, and what a step asks for by name.
    drivers: dict[str, Any] = field(default_factory=dict)

    @property
    def mutable(self) -> bool:
        """Whether ATF may make things here. An environment owned by *them* is looked at only."""
        return self.config.owner == "atf"

    def owner_of(self, resource: Any) -> str:
        """Who is responsible for this thing existing, here.

        Two levels, one word. An environment owned by *them* makes every resource in it observed,
        whatever the resource said; otherwise the declaration answers.
        """
        if self.config.owner == "them":
            return "them"
        return declaration_of(resource).owner

    def perform(self, resource: Any, method: str) -> Callable[..., Any]:
        """One of the resource's write methods, bound and ready, or a refusal naming what it lacks.

        `find` is the only method every resource answers. Leaving `create`, `update` or `delete` out
        says this kind of thing is never made, changed or removed, and asking for one raises
        `Unreachable` naming the kind and the method.
        """
        cls = type(resource)
        found = getattr(cls, method, None)
        if not callable(found) or found is getattr(Resource, method, None):
            declaration = declaration_of(resource)
            raise Unreachable(
                f"{declaration.kind}: the {declaration.system!r} system has no {method!r}, so one "
                f'is never {_DONE[method]}. Declare it `owner="them"` if that is the point.'
            )
        # Bound: resource.create() / resource.update(changes) / resource.delete().
        return getattr(resource, method)

    def can(self, resource: Any, method: str) -> bool:
        """Whether this resource's class offers one of the optional methods, `act` or `browse`."""
        return offers(type(resource), method)

    @property
    def transactional(self) -> list[str]:
        """Drivers that can wrap a test and undo everything it did."""
        return sorted(
            name
            for name, one in self.drivers.items()
            if offers(type(one), "begin") and offers(type(one), "rollback")
        )

    def begin(self) -> list[str]:
        """Open a transaction on every driver that offers one, and name the ones that opened.

        A driver that cannot be reached opens nothing and is left out, so its resources are made
        and taken away in the ordinary way.
        """
        opened: list[str] = []
        for name in self.transactional:
            try:
                self.drivers[name].begin()
            except Unreachable:
                continue
            opened.append(name)
        return opened

    def rollback(self, drivers: list[str]) -> None:
        """Undo what each of these drivers did since `begin`."""
        for name in drivers:
            one = self.drivers.get(name)
            if one is None:
                continue
            try:
                one.rollback()
            except Unreachable:
                continue

    def find_all(self, resources: list[Any]) -> dict[int, tuple[State, Payload | None]]:
        """Ask about several resources, one question per system where the class answers in bulk.

        Keyed by identity, which is what a graph node is. A class with no `find_many` is asked
        once per resource, and answers the same.
        """
        out: dict[int, tuple[State, Payload | None]] = {}
        by_system: dict[str, list[Any]] = {}
        for node in resources:
            by_system.setdefault(declaration_of(node).system, []).append(node)

        for _system, mine in by_system.items():
            for node in [one for one in mine if self.unresolved(one)]:
                out[id(node)] = (State.ABSENT, None)
            mine = [one for one in mine if id(one) not in out]
            if not mine:
                continue
            cls = type(mine[0])
            if not offers(cls, "find_many"):
                for node in mine:
                    out[id(node)] = self.find(node)
                continue
            try:
                answered = cls.find_many(mine)
            except Unreachable:
                out.update({id(node): (State.UNREACHABLE, None) for node in mine})
                continue
            for node, record in zip(mine, answered, strict=False):
                out[id(node)] = (State.PRESENT, record) if record is not None else (State.ABSENT, None)
        return out

    def unresolved(self, resource: Any) -> bool:
        """Whether what recognises this thing is still a hole `needs()` will fill.

        Nothing can be asked about a thing that has no identity yet. It is absent until resolution
        runs, and resolution runs when a test asks for one. A `Key` field with a plain default —
        never a hole at all — counts as written down from the start.
        """
        declaration = declaration_of(resource)
        values = resource.__atf_resource__.values
        return any(name in declaration.needs and name not in values for name in declaration.key)

    def find(self, resource: Any) -> tuple[State, Payload | None]:
        """Ask the environment whether this resource is there. The one question, asked every time.

        Nothing is written down between askings: a row deleted by hand or a database reset overnight
        gives the right answer immediately.
        """
        if self.unresolved(resource):
            return State.ABSENT, None
        try:
            found = resource.find()
        except Unreachable:
            return State.UNREACHABLE, None
        return (State.PRESENT, found) if found is not None else (State.ABSENT, None)


#: Settings whose value is a path. A relative one means "beside the manifest", never "beside
#: whatever directory this process happens to be in" — a suite must answer the same from anywhere.
PATH_SETTINGS = ("root", "cwd", "path", "dir", "directory")


def _against_manifest(settings: Payload, root: Path) -> Payload:
    """Resolve a relative path setting against the manifest's directory.

    A relative path in an environment's settings means "beside the manifest", whatever directory
    `atf` was invoked from.
    """
    out = dict(settings)
    for name, value in settings.items():
        if name in PATH_SETTINGS and isinstance(value, str) and value and not Path(value).is_absolute():
            out[name] = str((root / value).resolve())
    return out


def systems_used(suite: Suite) -> set[str]:
    """Every system the suite's declarations name."""
    return {declaration_of(kind).system for kind in suite.kinds.values() if declaration_of(kind).system}


def systems_wanted(suite: Suite, config: EnvironmentConfig) -> set[str]:
    """Every system to check is buildable: exactly the ones this suite's resources name."""
    return systems_used(suite)


def drivers_needed(suite: Suite, config: EnvironmentConfig) -> set[str]:
    """Every driver to build: the ones the wanted systems ask for, and the ones configured.

    A configured driver with no system behind it is built anyway — `shell` is the common case,
    since a test can run a command line without arranging anything through one.
    """
    wanted: set[str] = {
        name
        for system in systems_wanted(suite, config)
        if (cls := suite.adapters.get(system)) is not None
        for name in drivers_wanted(cls)
    }
    configured = {name for name in DRIVERS if name in config.settings}
    return wanted | configured


def build_ground(suite: Suite, env: str = "") -> Ground:
    """Build one driver per system this suite uses, against one environment.

    Every problem is collected before raising, so a manifest missing three blocks says so once.
    """
    config = suite.manifest.env(env)
    problems: list[str] = []
    drivers: dict[str, Any] = {}

    for name in sorted(drivers_needed(suite, config)):
        cls = DRIVERS.get(name)
        if cls is None:
            problems.append(
                f"no driver is registered as {name!r} — a class subclassing `Driver` and called "
                f"{name.title().replace('_', '')!r} should be imported by the suite"
            )
            continue
        settings = config.for_system(name)
        if settings is None:
            problems.append(f"the {name!r} driver has no settings in the {config.name!r} environment")
            continue
        try:
            checked = check(cls, "Settings", settings, f"environments.{config.name}.{name}")
            drivers[name] = cls(_against_manifest(checked, suite.manifest.root))
        except Exception as exc:  # noqa: BLE001 - whatever a driver's constructor raises is its own problem
            problems.append(f"the {name!r} driver could not be built: {type(exc).__name__}: {exc}")

    built: set[str] = set()
    for system in sorted(systems_wanted(suite, config)):
        cls = suite.adapters.get(system)
        if cls is None:
            problems.append(
                f"no system is registered for {system!r} — a class subclassing a system's own base "
                f"(`Record`, `Row`, ...) with `at=`/`system=` should be imported by the suite"
            )
            continue
        asked = drivers_wanted(cls)
        missing = [one for one in asked if one not in drivers]
        if missing:
            problems.append(
                f"the {system!r} system asks for the {', '.join(missing)} driver, and the "
                f"{config.name!r} environment configures none"
            )
            continue
        try:
            check_shape(system, cls)
        except Exception as exc:  # noqa: BLE001 - whatever the shape check raises is this system's problem
            problems.append(f"the {system!r} system could not be built: {type(exc).__name__}: {exc}")
            continue
        built.add(system)

    ground = Ground(suite=suite, config=config, drivers=drivers)
    # What `cls.http`/`self.sql`-style driver access reads. Set before the optional `check` below,
    # since a resource's own `check` may read a driver through its class the same way `create` does.
    _CURRENT_GROUND.set(ground)

    # An optional `check` lets a kind refuse a declaration it cannot honour, before a run. Only
    # asked of a resource whose system actually built — one that did not already said why.
    for node in suite.instances.values():
        if declaration_of(node).system not in built:
            continue
        say = getattr(node, "check", None)
        if callable(say) and (problem := say()):
            problems.append(problem)

    if problems:
        raise GroundError(
            f"the {config.name!r} environment is not ready:\n  - " + "\n  - ".join(problems)
        )
    return ground
