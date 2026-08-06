"""Lineage declared outright, on a base decorator every system decorator is built from.

A typed field was doing two jobs: saying what must exist first, and carrying the parent's key into
the child's row. They are not the same job, and welding them together means a dependency can only be
stated when the shape happens to have somewhere to put it.

`@resource` owns everything that belongs to ATF rather than to a system — `unique_by`, `when_absent`,
`scope`, `actions`, and now `depends_on`. `@adapter("sqlite")` mints `@sqlite(...)`, which is
`@resource` plus that system's own options. A suite writes `@sqlite`; ATF only ever reads `@resource`.

**`depends_on` takes kinds and instances, and which one it is says what is meant.**

- `depends_on=[Owner]` — *any* owner. Nothing in scope means the factory builds one.
- `depends_on=[primary]` — *that* owner.

Where the shape does hold the parent, passing it as a value says the same thing, so a foreign key is
still declared once.

An instance is built the way `DESIGN.md` builds one — `Owner(email="primary@example.com")`. The
decorator installs the `__init__` that records it, so the class a suite writes stays the class a
suite writes, and construction still touches nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DECLARED: dict[str, type] = {}
INSTANCES: dict[str, Any] = {}


@dataclass
class Declaration:
    """What a decorator recorded about a kind. Everything here is ATF's, not the system's."""

    system: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    unique_by: str | tuple[str, ...] = ""
    depends_on: list[Any] = field(default_factory=list)
    when_absent: str = "make"
    scope: str = "persistent"


def is_resource(value: Any) -> bool:
    """Whether this is a declared resource, rather than an ordinary value like a string."""
    return hasattr(type(value), "__atf__")


def name_of(value: Any) -> str:
    """A resource's name is its variable's name; one the factory built has none."""
    return value.__atf_name__


def values_of(value: Any) -> dict[str, Any]:
    """The shape: what an adapter writes."""
    return value.__atf_values__


# --- Declaring ----------------------------------------------------------------------------------


def _init(self: Any, *, depends_on: list[Any] | None = None, **values: Any) -> None:
    """Construction declares. It does not touch anything.

    A value that is itself a resource is a parent as well as a value — the foreign-key case, where
    the shape has room for the parent and writing the dependency again would be saying it twice.
    """
    # The fields are ordinary attributes, because that is how a test reads them:
    # `primary.email`, `groceries.owner.email` — arrange.md#asking-for-one.
    self.__dict__.update(values)
    self.__atf_values__ = values
    self.__atf_depends_on__ = [v for v in values.values() if is_resource(v)] + list(depends_on or [])
    self.__atf_name__ = ""
    self.__atf_from_factory__ = False


def _repr(self: Any) -> str:
    return f"{self.__atf_name__}:{type(self).__name__}" if self.__atf_name__ else f"{type(self).__name__}*"


def resource(
    *,
    depends_on: list[Any] | None = None,
    unique_by: str | tuple[str, ...] = "",
    when_absent: str = "make",
    scope: str = "persistent",
    system: str = "",
    options: dict[str, Any] | None = None,
):
    """The base decorator. Every system decorator is this one, with a system and its options bound."""

    def decorate(cls: type) -> type:
        cls.__atf__ = Declaration(
            system=system,
            options=dict(options or {}),
            unique_by=unique_by,
            depends_on=list(depends_on or []),
            when_absent=when_absent,
            scope=scope,
        )
        cls.__init__ = _init
        cls.__repr__ = _repr
        DECLARED[cls.__name__] = cls
        return cls

    return decorate


def adapter(system: str):
    """`@adapter("sqlite")` ships `@sqlite(...)` — `@resource`, plus that system's own options."""

    def system_decorator(
        *,
        depends_on: list[Any] | None = None,
        unique_by: str | tuple[str, ...] = "",
        when_absent: str = "make",
        scope: str = "persistent",
        **options: Any,
    ):
        return resource(
            depends_on=depends_on,
            unique_by=unique_by,
            when_absent=when_absent,
            scope=scope,
            system=system,
            options=options,
        )

    return system_decorator


sqlite = adapter("sqlite")


def scan(module: Any) -> None:
    """An instance's name is its variable's name, read by importing the module."""
    for name, value in vars(module).items():
        if is_resource(value) and not name.startswith("_") and not value.__atf_name__:
            value.__atf_name__ = name
            INSTANCES[name] = value


# --- Reading the graph ---------------------------------------------------------------------------


def parents(node: Any) -> list[Any]:
    """Everything this resource needs, with each `depends_on` entry read for what it is.

    An instance means that resource. A kind means any of them, so anything already supplied of that
    kind answers it, and when nothing has, the factory is asked for one.
    """
    supplied = [p for p in node.__atf_depends_on__ if is_resource(p)]
    wanted = [*type(node).__atf__.depends_on, *(p for p in node.__atf_depends_on__ if not is_resource(p))]

    resolved = list(supplied)
    for entry in wanted:
        if is_resource(entry):
            if not any(p is entry for p in resolved):
                resolved.append(entry)
            continue
        if any(type(p) is entry for p in resolved):
            continue  # a kind is satisfied by anything already supplied of that kind
        if not hasattr(entry, "factory"):
            raise ValueError(
                f"{node.__atf_name__ or 'a ' + type(node).__name__} needs {entry.__name__}, none is named, "
                f"and {entry.__name__} has no factory — name the one you mean"
            )
        built = entry.factory()
        built.__atf_from_factory__ = True
        resolved.append(built)
    return resolved


def closure(node: Any) -> list[Any]:
    """Everything that must exist before this one, parents first, each appearing once.

    This is the order things are made in, and the reverse of the order they are torn down in.
    """
    ordered: list[Any] = []
    seen: set[int] = set()

    def visit(current: Any, trail: tuple[Any, ...]) -> None:
        if any(t is current for t in trail):
            cycle = [*trail[next(i for i, t in enumerate(trail) if t is current) :], current]
            raise ValueError("a resource cannot need itself: " + " -> ".join(repr(r) for r in cycle))
        if id(current) in seen:
            return
        for parent in parents(current):
            visit(parent, (*trail, current))
        seen.add(id(current))
        ordered.append(current)

    visit(node, ())
    return ordered


def dependents(node: Any) -> list[Any]:
    """What breaks if this changes — `atf impact`, off the same edges."""
    return [other for other in INSTANCES.values() if other is not node and any(p is node for p in closure(other)[:-1])]


def unused() -> list[Any]:
    """What nothing asks for — `atf unused`, off the same edges."""
    needed = {id(p) for r in INSTANCES.values() for p in closure(r)[:-1]}
    return [r for r in INSTANCES.values() if id(r) not in needed]
