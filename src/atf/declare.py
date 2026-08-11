"""`@resource`, the system decorators built on it, and what a declaration records."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

WHEN_ABSENT = ("make", "require", "observe")
SCOPES = ("function", "session", "persistent")


class Unreachable(Exception):
    """Raised by an adapter when the system it talks to cannot be reached.

    The third thing an environment can say: `find` returning a record is present, `None` is absent,
    and this is a question that could not be asked. Never read as absence.
    """


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
    module: str = ""
    # The class's own annotations, as written. They are the shape a reader sees and nothing more —
    # no dependency is read from them, which is the whole point of `depends_on`.
    fields: dict[str, Any] = field(default_factory=dict)

    @property
    def kinds_needed(self) -> tuple[type, ...]:
        """The `depends_on` entries that name a kind, not a particular resource."""
        return tuple(entry for entry in self.depends_on if isinstance(entry, type))


@dataclass
class Instance:
    """What one declared resource is, beside the fields a suite gave it.

    Held under one attribute on the object, so a suite's own field names collide with one name.
    """

    kind: str
    values: dict[str, Any] = field(default_factory=dict)
    depends_on: list[Any] = field(default_factory=list)
    name: str = ""
    from_factory: bool = False
    #: What this resource was last found as, so a child can be checked against the parent it points
    #: at. Set when the resource is reconciled, and never read from anywhere else.
    identity: Any = None
    #: A copy a scenario made by patching a recognised field. Torn down with the scenario.
    ephemeral: bool = False
    #: Fields a scenario named in a variation. An explicit value always holds, even where the field
    #: would otherwise be left to whatever an action made of it.
    varied: frozenset[str] = frozenset()


# --- Reading a declared object -------------------------------------------------------------------


def is_resource(value: Any) -> bool:
    """Whether this is a declared resource. `False` for an ordinary value such as a string."""
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
    # The fields are ordinary attributes: `primary.email`, `groceries.owner.email`.
    self.__dict__.update(values)
    self.__atf_resource__ = Instance(
        kind=type(self).__name__,
        values=values,
        depends_on=[v for v in values.values() if is_resource(v)] + list(depends_on),
    )
    _check_declared(self, values)
    _check_recognisable(self, values)


def _check_declared(self: Any, values: dict[str, Any]) -> None:
    """Every value is a field the kind declares, or a parent. Anything else is refused here.

    A field holding another resource is exempt. That is the foreign-key case, and it is written on
    the instance while the class annotates only its own scalars: `TodoList(owner=primary, slug="…")`.
    """
    declaration = declaration_of(self)
    unknown = sorted(
        name
        for name, value in values.items()
        if name not in declaration.fields and not is_resource(value)
    )
    if unknown:
        declared = ", ".join(declaration.fields) or "no fields at all"
        raise DeclarationError(
            f"{declaration.kind} declares {declared}, and this one also sets {', '.join(unknown)}. "
            f"A resource carries the fields its class declares."
        )


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


def _fields(cls: type) -> dict[str, Any]:
    """The shape: every field this class annotates, and every one it inherits.

    A base class holding what two kinds share contributes its annotations to both.
    """
    found: dict[str, Any] = {}
    for ancestor in reversed(cls.__mro__):
        found.update(vars(ancestor).get("__annotations__", {}))
    return found


def _recognised(cls: type, system: str, unique_by: str | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """What recognises this resource: the adapter's own answer, or the one the suite wrote.

    An adapter over something that can only be recognised one way says so once, and a declaration
    then says nothing — a file is its path, and there was never a second way to put it.
    """
    fixed = getattr(ADAPTERS.get(system), "recognised_by", None)
    if fixed is not None:
        if unique_by:
            raise DeclarationError(
                f"{cls.__name__}: the {system!r} adapter recognises by {', '.join(fixed)}, so "
                f"`unique_by` says nothing it does not already know — remove it"
            )
        return tuple(fixed)
    return _recognition(cls, unique_by)


def _recognition(cls: type, unique_by: str | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """`unique_by` as a tuple of field names, whether one was written or several.

    Several is for a resource unique only in combination — a plan recognised by its code *within a
    region*. Every name is a field the resource carries. A parent is never one of them.
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
        recognised = _recognised(cls, _system, unique_by)
        fields = _fields(cls)
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
                module=cls.__module__,
                fields=fields,
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
        **options: Any,
    ):
        return resource(
            unique_by=unique_by,
            depends_on=depends_on,
            when_absent=when_absent,
            scope=scope,
            _system=name,
            _options=options,
        )

    decorator.__name__ = name
    decorator.__doc__ = f"Declare a resource of the `{name}` system."
    return decorator


ADAPTERS: dict[str, type] = {}


DRIVERS: dict[str, type] = {}


def driver(name: str):
    """Register a driver: the machinery an adapter works through, and a step can ask for by name.

    A driver is built once per environment from the `atf.yaml` block of its own name, and is what
    holds a connection, a browser or a shell.
    """

    def decorate(cls: type) -> type:
        seen = DRIVERS.get(name)
        if seen is not None and (seen.__module__, seen.__qualname__) != (cls.__module__, cls.__qualname__):
            raise DeclarationError(
                f"two drivers are called {name!r}: {seen.__module__}.{seen.__qualname__} "
                f"and {cls.__module__}.{cls.__qualname__}"
            )
        DRIVERS[name] = cls
        _bind(cls, "__atf_driver__", name)
        # The driver is bound into its own module under its name, so `from adapters.sqlite import
        # sqlite` reaches it and every adapter over it is an attribute: `@sqlite.row(...)`.
        module = sys.modules.get(cls.__module__)
        if module is not None and not hasattr(module, name):
            setattr(module, name, cls)
        return cls

    return decorate


#: Parameter names an adapter's `__init__` may take that are not drivers.
RESERVED = ("self", "args", "kwargs")


def _parameters(cls: type) -> tuple[str, ...]:
    import inspect  # noqa: PLC0415

    try:
        return tuple(inspect.signature(cls.__init__).parameters)
    except (TypeError, ValueError):
        return ()


def drivers_wanted(cls: type) -> tuple[str, ...]:
    """The drivers a class asks for, read off its `__init__` parameters by name."""
    return tuple(name for name in _parameters(cls) if name not in RESERVED)



def adapter(name: str, *, driver: str = ""):
    """Register an adapter class, and ship the `@<name>(...)` decorator that goes with it.

    `driver` is the machinery this kind of thing is made through. It namespaces the registration —
    `@adapter("row", driver="sqlite")` registers `sqlite.row` — and hangs the decorator off the
    driver, so a declaration says `@sqlite.row(...)` and names both at once.

    The decorator is bound into the module where the adapter is written, so that
    `from adapters.sqlite import sqlite` finds it — which is how every example in the documentation
    imports one. `atf.system(name)` returns the same object for anyone who would rather be explicit.

    An adapter takes its drivers as `__init__` parameters, by name. It carries `Options` — what the
    decorator accepts, per resource — and no settings of its own; those belong to a driver.
    """

    def decorate(cls: type) -> type:
        registered = f"{driver}.{name}" if driver else name
        # Compared by where it is written, so re-importing one file is a reload and not a clash.
        seen = ADAPTERS.get(registered)
        if seen is not None and (seen.__module__, seen.__qualname__) != (cls.__module__, cls.__qualname__):
            raise DeclarationError(
                f"two adapters are registered as {registered!r}: "
                f"{seen.__module__}.{seen.__qualname__} and {cls.__module__}.{cls.__qualname__}"
            )
        ADAPTERS[registered] = cls
        _bind(cls, "__atf_system__", registered)
        if driver:
            over = DRIVERS.get(driver)
            if over is None:
                raise DeclarationError(
                    f"{cls.__qualname__} is an adapter over the {driver!r} driver, and no "
                    f"`@driver({driver!r})` is registered above it"
                )
            if name in vars(over):
                raise DeclarationError(
                    f"the {driver!r} driver already has a {name!r}, so the {registered!r} adapter "
                    f"cannot hang its decorator there — rename one of them"
                )
            _bind(over, name, staticmethod(system_decorator(registered)))
        else:
            module = sys.modules.get(cls.__module__)
            if module is not None and not hasattr(module, name):
                setattr(module, name, system_decorator(registered))
        return cls

    return decorate


def system(name: str) -> Any:
    """The decorator a system ships, by name."""
    return system_decorator(name)
