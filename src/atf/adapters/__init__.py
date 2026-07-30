"""Adapter SPI and the factory registry. Importing this module registers the built-ins."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial
from importlib import import_module
from typing import Any, Protocol

from ..accessible import Control
from ..catalog import Node
from ..records import Record


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


class Showing(Protocol):
    """Optional: an adapter whose resources are things to *look at*, which can say what is on one.

    The reading surface for an interface is a **role** and an **accessible name** — `the button
    "Save"` — and never a selector, because a selector describes today's markup and a role and a
    name describe the thing. This is the seam that makes those claims mean one thing whichever
    adapter answers them: ATF's `html` system reads the page a server sent, its `browser` system
    reads the page after it has run, and a scenario says the same sentence to both.

    Acting on a control — clicking it, typing into it — is not here. Reading a response can never
    do it, and pretending otherwise would make a suite silently weaker on the machines that have no
    browser. Those steps ask for a driver and say so when there is none.

    `wait` is how long to keep looking, in milliseconds, where **0 means as long as this system
    usually would**. An interface that swaps a fragment in after a request has settled is
    asynchronous, not broken — and a claim that only ever looks at the first instant fails for a
    reason the scenario is not about. A negative claim passes a smaller number of its own, because
    waiting the full timeout for every "is not showing" would make a suite of them unusable.
    Something that cannot change while a scenario looks at it ignores the whole question.
    """

    def controls(self, role: str = "", name: str = "", *, wait: float = 0.0) -> list[Control]: ...

    def says(self, text: str, *, wait: float = 0.0) -> bool:
        """Whether these words are readable somewhere a person can see them."""
        ...

    def looking_at(self) -> str:
        """What is open, for a message to name — or `""` when nothing is."""
        ...


def can_show(adapter: Adapter) -> bool:
    return callable(getattr(adapter, "controls", None))


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


# Which module each built-in lives in, rather than the built-in itself. The registry needs to know
# the *names* of the systems ATF ships — a catalog naming an unregistered one is refused by name, and
# that check must not depend on anything being importable — but it does not need the code until
# something asks for an adapter.
#
# The difference is not academic. `rest` and the two that build on it reach for `httpx`, which is
# 80ms of an interpreter's life and, because httpx ships a command-line interface, brings `click` and
# `pygments` with it. Registering eagerly meant `atf --help` — and `atf init`, and `atf lint`, and
# `atf docs`, none of which speak HTTP — paid all of it before printing anything. A framework whose
# every invocation costs a third of a second teaches people to reach for something else.
_BUILT_IN = {
    "rest": (".rest", "RestAdapter"),
    "reference": (".reference", "ReferenceAdapter"),
    "browser": (".browser", "BrowserAdapter"),
    "html": (".html", "HtmlAdapter"),
    "command": (".command", "CommandAdapter"),
}


def _built_in(system: str, settings: dict[str, Any]) -> Adapter:
    """Import the module a built-in lives in, and build it. Called at most once per system per run."""
    module, name = _BUILT_IN[system]
    imported = import_module(module, __name__)
    made: Adapter = getattr(imported, name).from_settings(settings)
    return made


for _system in _BUILT_IN:
    register(_system, partial(_built_in, _system))

__all__ = [
    "Actionable",
    "Adapter",
    "Available",
    "Browsable",
    "Closeable",
    "AdapterFactory",
    "Context",
    "Control",
    "NoopDelete",
    "Record",
    "actions_of",
    "build",
    "Showing",
    "can_act",
    "can_browse",
    "can_show",
    "close_adapter",
    "register",
    "registered_systems",
    "unregister",
    "why_unavailable",
]
