"""One environment, live: an adapter per system, and what each answers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import lives
from .declare import (
    DRIVERS,
    Unreachable,
    declaration_of,
    drivers_wanted,
    instance_of,
    is_resource,
)
from .loader import Suite
from .manifest import Environment as EnvironmentConfig
from .spi import Parent, Record, Resource, State, check, check_shape, offers


def view(resource: Any, recognised_by: tuple[str, ...] = (), owner: str = "") -> Resource:
    """One declared thing, as a system sees it.

    Built at every call into a system, so a system never imports `values_of` or `declaration_of`
    and never holds ATF's own objects. `recognised_by` is what the system itself said tells one of
    these apart — see [Ground.recognition](#recognition). Nothing about it was typed by the author.
    """
    declaration = declaration_of(resource)
    record = instance_of(resource)
    scalars = {name: value for name, value in record.values.items() if not is_resource(value)}
    return Resource(
        kind=declaration.kind,
        name=record.name,
        options=dict(declaration.options),
        fields=dict(declaration.fields),
        owner=owner or declaration.owner,
        lives=lives.of(resource),
        values=scalars,
        identity={name: scalars[name] for name in recognised_by if name in scalars},
        parents={
            name: Parent(kind=declaration_of(value).kind, key=instance_of(value).identity)
            for name, value in record.values.items()
            if is_resource(value)
        },
    )


#: What each write method does, as a message says it.
_DONE = {"create": "made", "update": "changed", "delete": "removed"}


class GroundError(Exception):
    """Raised when an environment cannot be built, or cannot answer for a system it must.

    Named for the band the specification puts an environment in. Not `EnvironmentError`, which is
    a builtin alias of `OSError`.
    """


@dataclass
class Ground:
    """A suite pointed at one environment, with an adapter ready for each system it uses.

    The name is the band the specification puts an environment in. It holds no state about what has
    been made: presence is asked, never remembered.
    """

    suite: Suite
    config: EnvironmentConfig
    adapters: dict[str, Any] = field(default_factory=dict)
    #: The machinery each adapter works through, and what a step asks for by name.
    drivers: dict[str, Any] = field(default_factory=dict)
    #: What recognises each kind, as its own system answered it. Asked once, then held.
    recognitions: dict[str, tuple[str, ...]] = field(default_factory=dict)

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

    def recognition(self, resource: Any) -> tuple[str, ...]:
        """What tells one of these apart — **the system's answer, never the author's**.

        A file is recognised by its path. A row by whatever the table holds unique. A page by its
        URL. Asking the author to type it would be asking them to restate something the system
        already holds. A system says so with a `recognised_by` attribute where there is only ever
        one answer, or a `recognises` method where it has to look.
        """
        declaration = declaration_of(resource)
        held = self.recognitions.get(declaration.kind)
        if held is not None:
            return held
        adapter = self.adapter_for(resource)
        fixed = getattr(type(adapter), "recognised_by", None)
        if fixed is not None:
            answer = tuple(fixed)
        elif callable(getattr(adapter, "recognises", None)):
            answer = tuple(adapter.recognises(view(resource, owner=self.owner_of(resource))))
        else:
            raise GroundError(
                f"the {declaration.system!r} system does not say what recognises one of its things, "
                f"so ATF cannot tell one {declaration.kind} from another.\n"
                f"  A system answers that with a `recognised_by` attribute or a `recognises` method."
            )
        self.recognitions[declaration.kind] = answer
        return answer

    def view(self, resource: Any) -> Resource:
        """This resource as its system sees it, with recognition and ownership already answered."""
        return view(resource, self.recognition(resource), self.owner_of(resource))

    def adapter_for(self, resource: Any) -> Any:
        declaration = declaration_of(resource)
        try:
            return self.adapters[declaration.system]
        except KeyError:
            raise GroundError(
                f"the {declaration.system!r} system has no settings in the "
                f"{self.config.name!r} environment, and {declaration.kind} lives there"
            ) from None

    def perform(self, resource: Any, method: str) -> Any:
        """One of the adapter's write methods, or a refusal naming what this kind cannot do.

        `find` is the only method every adapter answers. Leaving `create`, `update` or `delete` out
        says this kind of thing is never made, changed or removed, and asking for one raises
        `Unreachable` naming the kind and the method.
        """
        adapter = self.adapter_for(resource)
        found = getattr(adapter, method, None)
        if not callable(found):
            declaration = declaration_of(resource)
            raise Unreachable(
                f"{declaration.kind}: the {declaration.system!r} system has no {method!r}, so one "
                f'is never {_DONE[method]}. Declare it `owner="them"` if that is the point.'
            )

        def call(_: Any, *rest: Any) -> Any:
            return found(self.view(resource), *rest)

        return call

    def can(self, resource: Any, method: str) -> bool:
        """Whether this resource's system offers one of the optional methods, `act` or `browse`."""
        return offers(type(self.adapter_for(resource)), method)

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

    def find_all(self, resources: list[Any]) -> dict[int, tuple[State, Record | None]]:
        """Ask about several resources, one question per system where the adapter answers in bulk.

        Keyed by identity, which is what a graph node is. An adapter with no `find_many` is asked
        once per resource, and answers the same.
        """
        out: dict[int, tuple[State, Record | None]] = {}
        by_system: dict[str, list[Any]] = {}
        for node in resources:
            by_system.setdefault(declaration_of(node).system, []).append(node)

        for system, mine in by_system.items():
            for node in [one for one in mine if self.unresolved(one)]:
                out[id(node)] = (State.ABSENT, None)
            mine = [one for one in mine if id(one) not in out]
            if not mine:
                continue
            adapter = self.adapters.get(system)
            if adapter is None or not offers(type(adapter), "find_many"):
                for node in mine:
                    out[id(node)] = self.find(node)
                continue
            try:
                answered = adapter.find_many([self.view(node) for node in mine])
            except Unreachable:
                out.update({id(node): (State.UNREACHABLE, None) for node in mine})
                continue
            for node, record in zip(mine, answered, strict=False):
                out[id(node)] = (State.PRESENT, record) if record is not None else (State.ABSENT, None)
        return out

    def unresolved(self, resource: Any) -> bool:
        """Whether what recognises this thing is still a hole `needs()` will fill.

        Nothing can be asked about a thing that has no identity yet. It is absent until resolution
        runs, and resolution runs when a test asks for one.
        """
        held = view(resource).values
        return any(key not in held for key in self.recognition(resource))

    def find(self, resource: Any) -> tuple[State, Record | None]:
        """Ask the environment whether this resource is there. The one question, asked every time.

        Nothing is written down between askings: a row deleted by hand or a database reset overnight
        gives the right answer immediately.
        """
        if self.unresolved(resource):
            return State.ABSENT, None
        try:
            found = self.adapter_for(resource).find(self.view(resource))
        except Unreachable:
            return State.UNREACHABLE, None
        return (State.PRESENT, found) if found is not None else (State.ABSENT, None)


#: Settings whose value is a path. A relative one means "beside the manifest", never "beside
#: whatever directory this process happens to be in" — a suite must answer the same from anywhere.
PATH_SETTINGS = ("root", "cwd", "path", "dir", "directory")


def _against_manifest(settings: Record, root: Path) -> Record:
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
    """Every system to build an adapter for: exactly the ones this suite's resources name."""
    return systems_used(suite)


def drivers_needed(suite: Suite, config: EnvironmentConfig) -> set[str]:
    """Every driver to build: the ones the wanted adapters ask for, and the ones configured.

    A configured driver with no adapter behind it is built anyway — `shell` is the common case,
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
    """Build one adapter per system this suite uses, against one environment.

    Every problem is collected before raising, so a manifest missing three blocks says so once.
    """
    config = suite.manifest.env(env)
    problems: list[str] = []
    drivers: dict[str, Any] = {}
    adapters: dict[str, Any] = {}

    for name in sorted(drivers_needed(suite, config)):
        cls = DRIVERS.get(name)
        if cls is None:
            problems.append(
                f"no driver is registered as {name!r} — an extension declaring "
                f"`@driver({name!r})` should be listed under `extensions:`"
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

    for system in sorted(systems_wanted(suite, config)):
        cls = suite.adapters.get(system)
        if cls is None:
            problems.append(
                f"no adapter is registered for the {system!r} system — "
                f"an extension declaring `@adapter({system!r})` should be listed under `extensions:`"
            )
            continue
        asked = drivers_wanted(cls)
        missing = [one for one in asked if one not in drivers]
        if missing:
            problems.append(
                f"the {system!r} adapter asks for the {', '.join(missing)} driver, and the "
                f"{config.name!r} environment configures none"
            )
            continue
        try:
            check_shape(system, cls)
            adapters[system] = cls(**{one: drivers[one] for one in asked})
        except Exception as exc:  # noqa: BLE001 - whatever an adapter's constructor raises is this system's problem
            problems.append(f"the {system!r} system could not be built: {type(exc).__name__}: {exc}")

    for kind, resource_class in sorted(suite.kinds.items()):
        declaration = declaration_of(resource_class)
        if declaration.system not in adapters:
            continue
        try:
            check(suite.adapters[declaration.system], "Options", declaration.options,
                  f"{kind}'s @{declaration.system}(...) options")
        except Exception as exc:  # noqa: BLE001
            problems.append(str(exc))

    # An optional `check` lets an adapter refuse a declaration it cannot honour, before a run.
    for node in suite.instances.values():
        adapter = adapters.get(declaration_of(node).system)
        say = getattr(adapter, "check", None)
        if callable(say) and (problem := say(view(node))):
            problems.append(problem)

    if problems:
        raise GroundError(
            f"the {config.name!r} environment is not ready:\n  - " + "\n  - ".join(problems)
        )
    return Ground(suite=suite, config=config, adapters=adapters, drivers=drivers)
