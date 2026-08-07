"""One environment, live: an adapter per system, and what each answers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .declare import Unreachable, declaration_of
from .loader import Suite
from .manifest import Environment as EnvironmentConfig
from .spi import Record, State, check, check_shape, offers


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

    @property
    def mutable(self) -> bool:
        return self.config.mutable

    def adapter_for(self, resource: Any) -> Any:
        system = declaration_of(resource).system
        try:
            return self.adapters[system]
        except KeyError:
            raise GroundError(
                f"the {system!r} system has no settings in the {self.config.name!r} environment, "
                f"and {declaration_of(resource).kind} lives there"
            ) from None

    def can(self, resource: Any, method: str) -> bool:
        """Whether this resource's system offers one of the optional methods, `act` or `browse`."""
        return offers(type(self.adapter_for(resource)), method)

    @property
    def transactional(self) -> list[str]:
        """Systems whose adapter can wrap a test and undo everything it did."""
        return sorted(
            name
            for name, adapter in self.adapters.items()
            if offers(type(adapter), "begin") and offers(type(adapter), "rollback")
        )

    def begin(self) -> list[str]:
        """Open a transaction on every system that offers one, and name the ones that opened.

        A system that cannot be reached opens nothing and is left out, so its resources are made
        and taken away in the ordinary way.
        """
        opened: list[str] = []
        for name in self.transactional:
            try:
                self.adapters[name].begin()
            except Unreachable:
                continue
            opened.append(name)
        return opened

    def rollback(self, systems: list[str]) -> None:
        """Undo what each of these systems did since `begin`."""
        for name in systems:
            adapter = self.adapters.get(name)
            if adapter is None:
                continue
            try:
                adapter.rollback()
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
            adapter = self.adapters.get(system)
            if adapter is None or not offers(type(adapter), "find_many"):
                for node in mine:
                    out[id(node)] = self.find(node)
                continue
            try:
                found = adapter.find_many(mine)
            except Unreachable:
                out.update({id(node): (State.UNREACHABLE, None) for node in mine})
                continue
            for node in mine:
                record = found.get(id(node))
                out[id(node)] = (State.PRESENT, record) if record is not None else (State.ABSENT, None)
        return out

    def find(self, resource: Any) -> tuple[State, Record | None]:
        """Ask the environment whether this resource is there. The one question, asked every time.

        Nothing is written down between askings: a row deleted by hand or a database reset overnight
        gives the right answer immediately.
        """
        try:
            found = self.adapter_for(resource).find(resource)
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
    """Every system to build an adapter for: the ones resources use, and the ones configured.

    A system with settings and no resources is included — `command` is the common case, since
    `shell` runs command lines for tests that arrange nothing through it. A configured system ATF
    has no adapter for is ignored.
    """
    configured = {system for system in config.settings if system in suite.adapters}
    return systems_used(suite) | configured


def build_ground(suite: Suite, env: str = "") -> Ground:
    """Build one adapter per system this suite uses, against one environment.

    Every problem is collected before raising, so a manifest missing three blocks says so once.
    """
    config = suite.manifest.env(env)
    problems: list[str] = []
    adapters: dict[str, Any] = {}

    for system in sorted(systems_wanted(suite, config)):
        cls = suite.adapters.get(system)
        if cls is None:
            problems.append(
                f"no adapter is registered for the {system!r} system — "
                f"an extension declaring `@adapter({system!r})` should be listed under `extensions:`"
            )
            continue
        settings = config.for_system(system)
        if settings is None:
            problems.append(f"the {system!r} system has no settings in the {config.name!r} environment")
            continue
        try:
            check_shape(system, cls)
            checked = check(cls, "Settings", settings, f"environments.{config.name}.{system}")
            adapters[system] = cls(_against_manifest(checked, suite.manifest.root))
        except Exception as exc:  # noqa: BLE001 - whatever an adapter's constructor raises is this system's problem
            problems.append(f"the {system!r} system could not be built: {type(exc).__name__}: {exc}")

    for kind, cls in sorted(suite.kinds.items()):
        declaration = declaration_of(cls)
        adapter = suite.adapters.get(declaration.system)
        if adapter is None or declaration.system not in adapters:
            continue
        try:
            check(adapter, "Options", declaration.options, f"{kind}'s @{declaration.system}(...) options")
        except Exception as exc:  # noqa: BLE001
            problems.append(str(exc))

    # An optional `check` lets an adapter refuse a declaration it cannot honour, before a run.
    for node in suite.instances.values():
        adapter = adapters.get(declaration_of(node).system)
        say = getattr(adapter, "check", None)
        if callable(say) and (problem := say(node)):
            problems.append(problem)

    if problems:
        raise GroundError(
            f"the {config.name!r} environment is not ready:\n  - " + "\n  - ".join(problems)
        )
    return Ground(suite=suite, config=config, adapters=adapters)
