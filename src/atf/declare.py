"""The declaration layer: `@resource`, the system decorators built on it, and what they record.

A resource is declared as a class and instantiated at module level. **Construction declares; it does
not touch anything.** What a resource needs is written with `depends_on` and nothing else — no
annotation carries a dependency, because a dependency does not always have a field to live in. A
report written per owner that stores only its slug has nowhere to put an `owner`, and it still needs
the owner.

`@resource` owns what belongs to ATF: `unique_by`, `depends_on`, `when_absent`, `scope`, `actions`.
`@adapter("sqlite")` mints `@sqlite(...)`, which is `@resource` with a system and that system's own
options bound. A suite writes `@sqlite`; ATF only ever reads `@resource`.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

WHEN_ABSENT = ("make", "require", "observe")
SCOPES = ("function", "session", "persistent")


class Unreachable(Exception):
    """Raised by an adapter when the system it talks to cannot be reached.

    This is the third thing an environment can say. `find` returning a record means present, `None`
    means absent, and this means the question could not be asked — which is never read as absence,
    because ATF does not try to create a row in a database it could not connect to.
    """


@dataclass(frozen=True)
class Update:
    """A change an action makes to a resource: `actions={"complete": Update(done=True)}`."""

    values: dict[str, Any]

    def __init__(self, **values: Any) -> None:
        object.__setattr__(self, "values", values)


class DeclarationError(Exception):
    """Raised when a declaration cannot be read as one. Always at load, never inside a test."""


@dataclass(frozen=True)
class Declaration:
    """What a decorator recorded about a kind. Everything here belongs to ATF, not to a system."""

    kind: str
    system: str
    options: dict[str, Any] = field(default_factory=dict)
    unique_by: tuple[str, ...] = ()
    depends_on: tuple[Any, ...] = ()
    when_absent: str = "make"
    scope: str = "persistent"
    actions: dict[str, Update] = field(default_factory=dict)
    module: str = ""
    # The class's own annotations, as written. They are the shape a reader sees and nothing more —
    # no dependency is read from them, which is the whole point of `depends_on`.
    fields: dict[str, Any] = field(default_factory=dict)

    @property
    def kinds_needed(self) -> tuple[type, ...]:
        """The entries that name a kind rather than a particular resource."""
        return tuple(entry for entry in self.depends_on if isinstance(entry, type))


@dataclass
class Instance:
    """What one declared resource is, beside the fields a suite gave it.

    Held under a single attribute on the object so that a suite's own field names collide with one
    name rather than with several.
    """

    kind: str
    values: dict[str, Any] = field(default_factory=dict)
    depends_on: list[Any] = field(default_factory=list)
    name: str = ""
    from_factory: bool = False


# --- Reading a declared object -------------------------------------------------------------------


def is_resource(value: Any) -> bool:
    """Whether this is a declared resource, rather than an ordinary value like a string."""
    return hasattr(type(value), "__atf_declaration__")


def declaration_of(value: Any) -> Declaration:
    """The kind's declaration, whether asked of the class or of one of its instances."""
    owner = value if isinstance(value, type) else type(value)
    return owner.__atf_declaration__


def instance_of(value: Any) -> Instance:
    """ATF's record of one particular resource."""
    return value.__atf_resource__


def name_of(value: Any) -> str:
    """A resource's name is its variable's name. One the factory built has none."""
    return instance_of(value).name


def values_of(value: Any) -> dict[str, Any]:
    """The shape: the fields a suite declared, which is what an adapter writes."""
    return instance_of(value).values


# --- The decorators -------------------------------------------------------------------------------


def _init(self: Any, **values: Any) -> None:
    """Construction declares. It does not touch anything.

    A value that is itself a resource is a parent as well as a value — the foreign-key case, where
    the shape has room for the parent and writing the dependency again would be saying it twice.
    """
    depends_on = values.pop("depends_on", None) or []
    if not isinstance(depends_on, list | tuple):
        raise DeclarationError(f"{type(self).__name__}: depends_on must be a list of resources")
    # The fields are ordinary attributes, because that is how a test reads them: `primary.email`,
    # `groceries.owner.email`.
    self.__dict__.update(values)
    self.__atf_resource__ = Instance(
        kind=type(self).__name__,
        values=values,
        depends_on=[v for v in values.values() if is_resource(v)] + list(depends_on),
    )
    _check_recognisable(self, values)


def _check_recognisable(self: Any, values: dict[str, Any]) -> None:
    """Every field `unique_by` names must be a declared scalar of this resource.

    Recognition is what says *which* resource this is, so a `unique_by` naming a field nothing
    declares gives an adapter an empty identity — and an empty identity matches whatever comes
    first. That is the quietest way to write to the wrong row, so it is refused at declaration.
    """
    declaration = declaration_of(self)
    for name in declaration.unique_by:
        if name not in values:
            declared = ", ".join(sorted(values)) or "nothing"
            raise DeclarationError(
                f"{declaration.kind} is recognised by {name!r}, and this one declares {declared}. "
                f"A resource is recognised by the fields it carries."
            )
        if is_resource(values[name]):
            raise DeclarationError(
                f"{declaration.kind} is recognised by {name!r}, which holds another resource. "
                f"Recognition is by declared values; write the dependency in `depends_on` and "
                f"recognise this one by a field of its own."
            )


def _repr(self: Any) -> str:
    record = instance_of(self)
    return f"{record.name}:{record.kind}" if record.name else f"{record.kind}(unnamed)"


def _bind(cls: type, name: str, value: Any) -> None:
    """Attach one piece of ATF's bookkeeping to a declared class.

    A class object has no static home for these, so they go on through `setattr` in one place rather
    than as four assignments a type checker has to be told to overlook.
    """
    setattr(cls, name, value)


def _recognition(cls: type, unique_by: str | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """`unique_by` as a tuple of field names, whether one was written or several.

    Several is for a resource unique only in combination — a plan recognised by its code *within a
    region*. They are the fields the resource carries, and never a parent: a dependency goes in
    `depends_on`, and what a parent is called in a row is the adapter's business rather than ATF's.
    """
    if isinstance(unique_by, str):
        return (unique_by,) if unique_by else ()
    if not isinstance(unique_by, list | tuple) or not all(isinstance(name, str) and name for name in unique_by):
        raise DeclarationError(
            f"{cls.__name__}: unique_by is {unique_by!r}; it is a field name, or several of them"
        )
    if len(set(unique_by)) != len(unique_by):
        raise DeclarationError(f"{cls.__name__}: unique_by names the same field twice: {unique_by!r}")
    return tuple(unique_by)


def resource(
    *,
    unique_by: str | tuple[str, ...] | list[str] = "",
    depends_on: list[Any] | tuple[Any, ...] | None = None,
    when_absent: str = "make",
    scope: str = "persistent",
    actions: dict[str, Update] | None = None,
    _system: str = "",
    _options: dict[str, Any] | None = None,
):
    """The base decorator. Every system decorator is this one, with a system and its options bound.

    `_system` and `_options` are how `@adapter` binds itself to it, and are not written by a suite.
    """

    def decorate(cls: type) -> type:
        if when_absent not in WHEN_ABSENT:
            raise DeclarationError(
                f"{cls.__name__}: when_absent is {when_absent!r}; it is one of {', '.join(WHEN_ABSENT)}"
            )
        if scope not in SCOPES:
            raise DeclarationError(f"{cls.__name__}: scope is {scope!r}; it is one of {', '.join(SCOPES)}")
        recognised = _recognition(cls, unique_by)
        for entry in depends_on or ():
            if not (isinstance(entry, type) and is_declared(entry)) and not is_resource(entry):
                raise DeclarationError(
                    f"{cls.__name__}: depends_on holds {entry!r}, which is neither a declared "
                    f"resource nor one of their kinds"
                )

        _bind(
            cls,
            "__atf_declaration__",
            Declaration(
                kind=cls.__name__,
                system=_system,
                options=dict(_options or {}),
                unique_by=recognised,
                depends_on=tuple(depends_on or ()),
                when_absent=when_absent,
                scope=scope,
                actions=dict(actions or {}),
                module=cls.__module__,
                fields=dict(vars(cls).get("__annotations__", {})),
            ),
        )
        _bind(cls, "__init__", _init)
        _bind(cls, "__repr__", _repr)
        return cls

    return decorate


def is_declared(cls: Any) -> bool:
    """Whether this class has been through a system decorator."""
    return isinstance(cls, type) and "__atf_declaration__" in vars(cls)


def system_decorator(name: str):
    """The `@sqlite(...)` a system ships: `@resource`, plus that system's own options."""

    def decorator(
        *,
        unique_by: str | tuple[str, ...] | list[str] = "",
        depends_on: list[Any] | tuple[Any, ...] | None = None,
        when_absent: str = "make",
        scope: str = "persistent",
        actions: dict[str, Update] | None = None,
        **options: Any,
    ):
        return resource(
            unique_by=unique_by,
            depends_on=depends_on,
            when_absent=when_absent,
            scope=scope,
            actions=actions,
            _system=name,
            _options=options,
        )

    decorator.__name__ = name
    decorator.__doc__ = f"Declare a resource of the `{name}` system."
    return decorator


ADAPTERS: dict[str, type] = {}


def adapter(name: str):
    """Register an adapter class, and ship the `@<name>(...)` decorator that goes with it.

    The decorator is bound into the module where the adapter is written, so that
    `from adapters.sqlite import sqlite` finds it — which is how every example in the documentation
    imports one. `atf.system(name)` returns the same object for anyone who would rather be explicit.
    """

    def decorate(cls: type) -> type:
        # Compared by where it is written rather than by identity, so re-importing the same file —
        # which the editor does, and which loading a second suite forces — is a reload and not a
        # clash. Two different files claiming one system name is the real mistake.
        seen = ADAPTERS.get(name)
        if seen is not None and (seen.__module__, seen.__qualname__) != (cls.__module__, cls.__qualname__):
            raise DeclarationError(
                f"two adapters are called {name!r}: {seen.__module__}.{seen.__qualname__} "
                f"and {cls.__module__}.{cls.__qualname__}"
            )
        ADAPTERS[name] = cls
        _bind(cls, "__atf_system__", name)
        module = sys.modules.get(cls.__module__)
        if module is not None and not hasattr(module, name):
            setattr(module, name, system_decorator(name))
        return cls

    return decorate


def system(name: str) -> Any:
    """The decorator a system ships, by name."""
    return system_decorator(name)
