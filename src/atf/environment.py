"""An environment, live: the adapters built against it and what they answer.

**One adapter instance is built per system, per environment**, constructed with that environment's
settings and holding its own connection. Nothing here decides what to do about a resource — that is
[reconcile](reconcile.py). This decides *who to ask*.

A system a resource needs but the environment does not configure stops the run at start-up, naming
the system and the environment, rather than failing inside the first test.
"""

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

    Named for the band the specification puts an environment in, rather than `EnvironmentError`,
    which is a builtin alias of `OSError` and would be caught by anything catching one.
    """


@dataclass
class Ground:
    """A suite pointed at one environment, with an adapter ready for each system it uses.

    The name is the band the specification puts an environment in. It holds no state about what has
    been made — presence is asked, never remembered, which is why there is no state file.
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
    """Resolve a relative path setting against the manifest's directory rather than the cwd.

    ATF's own suite found this: an inner manifest saying `filesystem: { root: . }` was writing into
    whatever directory `atf` was invoked from, so `find` asked about one place and `create` wrote to
    another. A manifest describes a suite, and a suite does not move when you cd.
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

    A system with settings and no resources is not a mistake — `command` is the common case, since
    `shell` runs command lines for tests that arrange nothing through that system. A configured
    system ATF has no adapter for is ignored rather than fatal, so an environment shared with
    another tool does not have to be trimmed to suit this one.
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

    if problems:
        raise GroundError(
            f"the {config.name!r} environment is not ready:\n  - " + "\n  - ".join(problems)
        )
    return Ground(suite=suite, config=config, adapters=adapters)
