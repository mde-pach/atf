"""Adapter SPI and the factory registry. Importing this module registers the built-ins."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

from ..catalog import Node

Record = dict[str, Any]


class Context(Protocol):
    """What an adapter may use from the materializer that drives it."""

    env: str

    def resolve(self, value: Any) -> Any:
        """Resolve `${...}` placeholders; raises `atf.placeholders.Unresolved`."""
        ...

    def cached(self, key: str, loader: Callable[[], Any]) -> Any:
        """Memoise a remote listing for the duration of a materialize pass."""
        ...

    def invalidate_cache(self) -> None: ...


class Adapter(Protocol):
    def find(self, node: Node, ctx: Context) -> Record | None: ...

    def create(self, node: Node, body: Record, ctx: Context) -> Record: ...

    def delete(self, node: Node, record: Record, ctx: Context) -> None: ...


class Browsable(Protocol):
    """Optional: an adapter that can enumerate what a resource type already has in an environment.

    `find` answers "is this one node there?"; browsing answers "what is there at all?", which is
    what lets a catalog be written from an environment instead of typed from scratch. The node
    passed in is a probe carrying the type's config and whatever body fields scope the listing.
    """

    def browse(self, node: Node, ctx: Context, limit: int = 200) -> list[Record]: ...


def can_browse(adapter: Adapter) -> bool:
    return callable(getattr(adapter, "browse", None))


class Actionable(Protocol):
    """Optional: an adapter that can *do* something to a resource, not only read or make one.

    ATF could always create and delete, because those are what a catalog is for. Everything else a
    system can do — complete a task, close an account, retry a job — was a step some project had to
    write, including the ones that are one HTTP call the adapter already knows how to make.

    An adapter offers *mechanical* verbs; the catalog names a *domain* action in terms of them; the
    spec says the domain action:

        task:
          system: rest
          actions:
            complete: { patch: { done: true } }

        When I complete the task "milk"

    The action's body is adapter configuration, exactly as `path` is — ATF validates its shape and
    reads nothing into it. Because `actions` is data it is also *enumerable*, which is what lets the
    composer offer it in a dropdown, and it is the same property that made assertions composable.

    Returns the record as it is after the action, or `None` when the system says nothing useful —
    in which case the assertions after it read the resource back for themselves, as they always do.
    """

    def act(self, node: Node, record: Record, action: str, ctx: Context) -> Record | None: ...


def can_act(adapter: Adapter) -> bool:
    return callable(getattr(adapter, "act", None))


def actions_of(entry: dict[str, Any]) -> list[str]:
    """The domain actions a resource type declares, in the order the catalog wrote them."""
    declared = entry.get("actions")
    return [str(name) for name in declared] if isinstance(declared, dict) else []


class Available(Protocol):
    """Optional: an adapter that can say it cannot work here, and why.

    Some systems are not a matter of configuration. A browser adapter needs a browser installed; a
    device farm needs the farm reachable. A scenario that needs one should *skip* on a machine
    without it, saying what is missing — not fail, which reads as a broken suite, and not pass,
    which is a lie.

    Returns the reason it is unavailable, or `""` when it is fine. A reason is required because a
    skip nobody can act on is a skip nobody removes.
    """

    def unavailable(self) -> str: ...


def why_unavailable(adapter: Adapter) -> str:
    """Why this adapter cannot work here, or `""`. An adapter that does not say is available."""
    asked = getattr(adapter, "unavailable", None)
    if not callable(asked):
        return ""
    try:
        return str(asked() or "")
    except Exception as exc:  # noqa: BLE001 - a broken check is itself a reason to skip
        return f"checking whether it is available raised {type(exc).__name__}: {exc}"


class Closeable(Protocol):
    """Optional: an adapter holding a connection, session or browser can release it here."""

    def close(self) -> None: ...


def close_adapter(adapter: Adapter) -> None:
    """Release an adapter's resources if it has any. Never raises."""
    closer = getattr(adapter, "close", None)
    if closer is None:
        return
    try:
        closer()
    except Exception:  # noqa: BLE001 - closing must never fail a run
        logging.getLogger("atf.adapters").warning("closing %s failed", type(adapter).__name__)


AdapterFactory = Callable[[dict[str, Any]], Adapter]

_REGISTRY: dict[str, AdapterFactory] = {}


def register(system: str, factory: AdapterFactory) -> None:
    _REGISTRY[system] = factory


def build(system: str, settings: dict[str, Any]) -> Adapter:
    try:
        factory = _REGISTRY[system]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "none"
        raise KeyError(f"no adapter registered for system {system!r} (registered: {known})") from None
    return factory(settings)


def registered_systems() -> set[str]:
    return set(_REGISTRY)


def unregister(system: str) -> None:
    _REGISTRY.pop(system, None)


class NoopDelete:
    """Mixin for backends without deletion: teardown is a no-op."""

    def delete(self, node: Node, record: Record, ctx: Context) -> None:
        return None


def _register_builtins() -> None:
    from .reference import ReferenceAdapter
    from .rest import RestAdapter

    register("rest", RestAdapter.from_settings)
    register("reference", ReferenceAdapter.from_settings)


_register_builtins()

__all__ = [
    "Actionable",
    "Adapter",
    "Available",
    "Browsable",
    "Closeable",
    "AdapterFactory",
    "Context",
    "NoopDelete",
    "Record",
    "actions_of",
    "build",
    "can_act",
    "can_browse",
    "close_adapter",
    "register",
    "registered_systems",
    "unregister",
    "why_unavailable",
]
