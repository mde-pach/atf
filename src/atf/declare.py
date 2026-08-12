"""`needs()`, the system decorators, and what a declaration records: `owner`, `lives`, `needs`."""

from __future__ import annotations

import sys
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

#: Who is responsible for a thing existing. `atf` may make it; `them` means ATF only looks.
OWNERS = ("atf", "them")

#: The three spans a resource can live for, longest first. Nobody picks one — it is read off the
#: suite — but `lives=` overrides the reading for what ATF cannot see.
FOREVER, THE_RUN, THE_TEST = "forever", "the run", "the test"
SPANS = (FOREVER, THE_RUN, THE_TEST)


class Unreachable(Exception):
    """Raised by a system when the thing it talks to cannot be reached.

    The third thing an environment can say: `find` returning a record is present, `None` is absent,
    and this is a question that could not be asked. Never read as absence.
    """


class DeclarationError(Exception):
    """Raised when a declaration cannot be read as one. Always at load, never inside a test."""


# --- needs() --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Need:
    """How to get one when nobody gave one — the whole of resolution, at the hole it fills.

    `resolver` is what produces the value: another declared kind, or any callable at all. A callable
    may itself take resources, which is what makes a separate factory concept unnecessary.
    """

    #: What was written inside `needs(...)`, before the annotation was consulted. `None` is bare.
    written: Any = None
    #: What resolution actually calls or builds, after a bare `needs()` read the annotation.
    resolver: Any = None
    #: The declared kind this need is an edge to, where it is one. Otherwise nothing.
    kind: type | None = None
    #: The field this fills, for a message.
    where: str = ""


def needs(resolver: Any = None) -> Any:
    """Declare how a field is filled when nobody gave it a value.

    Bare, it resolves whatever the annotation names — the field says `Owner`, so writing `Owner`
    again would be saying it twice. With an argument it names something else: another declared kind,
    or any callable, which is where a team's own generator plugs in.

    ATF never produces a value itself. Knowing what a valid email is means owning a domain
    vocabulary, so `needs(fake.unique.email)` is the shape, and the provider is yours.
    """
    return Need(written=resolver)


def _hints(cls: type) -> dict[str, Any]:
    """Every annotation on this class, with string annotations resolved where they can be.

    A suite module may say `from __future__ import annotations`, so every annotation may be a string.
    """
    try:
        return typing.get_type_hints(cls)
    except Exception:  # noqa: BLE001 - an annotation that will not resolve is reported per field
        return {}


def _read_needs(cls: type, annotations: dict[str, Any]) -> dict[str, Need]:
    """Every `needs()` written as a default on this class, resolved to what it will call.

    The class attribute goes: a field left unfilled must read as absent, not as ATF's bookkeeping.
    """
    hints = _hints(cls)
    out: dict[str, Need] = {}
    for name in annotations:
        written = getattr(cls, name, None)
        if not isinstance(written, Need):
            continue
        annotation = hints.get(name, annotations.get(name))
        resolver = written.written if written.written is not None else annotation
        if resolver is None or (written.written is None and not is_declared(resolver)):
            said = getattr(annotation, "__name__", None) or str(annotation) or "nothing"
            raise DeclarationError(
                f"{cls.__name__}.{name}: `needs()` on its own resolves whatever the annotation "
                f"names, and this one says {said}, which is not a declared kind.\n"
                f"  Give it something that produces one: `needs(a_slug)`, `needs(fake.email)`."
            )
        if not is_declared(resolver) and not callable(resolver):
            raise DeclarationError(
                f"{cls.__name__}.{name}: `needs({resolver!r})` names neither a declared kind nor "
                f"anything callable"
            )
        out[name] = Need(
            written=written.written,
            resolver=resolver,
            kind=resolver if is_declared(resolver) else None,
            where=f"{cls.__name__}.{name}",
        )
        if name in vars(cls):
            delattr(cls, name)
    return out


@dataclass(frozen=True)
class Declaration:
    """What a decorator recorded about a kind. Everything here belongs to ATF, not to a system."""

    kind: str
    system: str
    options: dict[str, Any] = field(default_factory=dict)
    #: How each unfilled field is filled — lineage and value generation, in one place.
    needs: dict[str, Need] = field(default_factory=dict)
    #: `atf` or `them`. Who is responsible for one of these existing.
    owner: str = "atf"
    #: An override for the span ATF would otherwise read off the suite. Empty means derived.
    lives: str = ""
    module: str = ""
    #: The class's own annotations, as written. The shape a reader sees, and nothing more.
    fields: dict[str, Any] = field(default_factory=dict)

    @property
    def kinds_needed(self) -> tuple[type, ...]:
        """The kinds this one has an edge to, read off the `needs()` written at each field."""
        return tuple(dict.fromkeys(need.kind for need in self.needs.values() if need.kind is not None))

    def need_for(self, field_name: str) -> Need | None:
        return self.needs.get(field_name)


@dataclass
class Instance:
    """What one declared resource is, beside the fields a suite gave it.

    Held under one attribute on the object, so a suite's own field names collide with one name.
    """

    kind: str
    values: dict[str, Any] = field(default_factory=dict)
    depends_on: list[Any] = field(default_factory=list)
    name: str = ""
    #: Whether resolution built this one. `False` for one a module names.
    built: bool = False
    #: Fields left to resolution. A thing with any of these is factorised.
    resolved: set[str] = field(default_factory=set)
    #: What this resource was last found as, so a child can be checked against the parent it points
    #: at. Set when the resource is reconciled, and never read from anywhere else.
    identity: Any = None
    #: A copy a scenario made by patching a recognised field. Torn down with the scenario.
    ephemeral: bool = False
    #: Fields a scenario took away with `without`. Resolution leaves these alone.
    dropped: frozenset[str] = frozenset()
    #: Fields a scenario named in a variation. An explicit value always holds, even where the field
    #: would otherwise be left to whatever an action made of it.
    varied: frozenset[str] = frozenset()

    @property
    def factorised(self) -> bool:
        """Whether anything about this one is left to resolution."""
        return self.built or bool(self.resolved)


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
    """A resource's name is its variable's name. One resolution built has none."""
    return instance_of(value).name


def values_of(value: Any) -> dict[str, Any]:
    """The shape: the fields a suite declared, which is what a system writes."""
    return instance_of(value).values


# --- The decorators -------------------------------------------------------------------------------


def _init(self: Any, **values: Any) -> None:
    """Construction declares. It does not touch anything.

    A value that is itself a resource is a parent as well as a value — the foreign-key case, where
    the shape has room for the parent and writing the dependency again would be saying it twice.
    """
    # A `Need` reaching here would be a field left to resolution and then handed back as a value.
    values = {name: value for name, value in values.items() if not isinstance(value, Need)}
    self.__dict__.update(values)
    declaration = declaration_of(self)
    self.__atf_resource__ = Instance(
        kind=declaration.kind,
        values=values,
        depends_on=[v for v in values.values() if is_resource(v)],
        # Which holes resolution will fill is known now, not when it fills them. A thing is
        # factorised the moment it leaves one open, and how long it lives follows from that.
        resolved={name for name in declaration.needs if name not in values},
    )
    _check_declared(self, values)


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


def resource(
    *,
    owner: str = "atf",
    lives: str = "",
    _system: str = "",
    _options: dict[str, Any] | None = None,
):
    """The base decorator. Every system decorator is this one, with a system and its options bound.

    `_system` and `_options` are how a system binds itself to it, and are not written by a suite.
    """

    def decorate(cls: type) -> type:
        if owner not in OWNERS:
            raise DeclarationError(
                f"{cls.__name__}: owner is {owner!r}; it is {' or '.join(repr(one) for one in OWNERS)} — "
                f"who is responsible for one of these existing"
            )
        if lives and lives not in SPANS:
            raise DeclarationError(
                f"{cls.__name__}: lives is {lives!r}; it is one of {', '.join(repr(one) for one in SPANS)}.\n"
                f"  Leave it out unless ATF cannot see the truth: the span is read off the suite."
            )
        fields = _fields(cls)
        _bind(
            cls,
            "__atf_declaration__",
            Declaration(
                kind=cls.__name__,
                system=_system,
                options=dict(_options or {}),
                needs=_read_needs(cls, fields),
                owner=owner,
                lives=lives,
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
    """The `@sql.row(...)` a system ships: `@resource`, plus that system's own options."""

    def decorator(*, owner: str = "atf", lives: str = "", **options: Any):
        return resource(owner=owner, lives=lives, _system=name, _options=options)

    decorator.__name__ = name
    decorator.__doc__ = f"Declare a thing of the `{name}` system."
    return decorator


ADAPTERS: dict[str, type] = {}


DRIVERS: dict[str, type] = {}


def driver(name: str):
    """Register a driver: the machinery an adapter works through, and a step can ask for by name.

    A driver is built once per environment from the `atf.yaml` block of its own name, and is what
    holds a connection, a browser or a shell. Internal structure — a team writing an extension meets
    one word, and it is *system*.
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
        # The driver is bound into its own module under its name, so `from systems.sqlite import
        # sqlite` reaches it and every adapter over it is an attribute: `@sqlite.row(...)`.
        module = sys.modules.get(cls.__module__)
        if module is not None and not hasattr(module, name):
            setattr(module, name, cls)
        return cls

    return decorate


#: Parameter names an adapter's `__init__` may take that are not drivers.
RESERVED = ("self", "args", "kwargs")


def _parameters(cls: type) -> tuple[str, ...]:
    import inspect

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

    An adapter takes its drivers as `__init__` parameters, by name. It carries `Options` — what the
    decorator accepts, per resource — and no settings of its own; those belong to a driver.
    """

    def decorate(cls: type) -> type:
        registered = f"{driver}.{name}" if driver else name
        # Compared by where it is written, so re-importing one file is a reload and not a clash.
        seen = ADAPTERS.get(registered)
        if seen is not None and (seen.__module__, seen.__qualname__) != (cls.__module__, cls.__qualname__):
            raise DeclarationError(
                f"two systems are registered as {registered!r}: "
                f"{seen.__module__}.{seen.__qualname__} and {cls.__module__}.{cls.__qualname__}"
            )
        ADAPTERS[registered] = cls
        _bind(cls, "__atf_system__", registered)
        if driver:
            over = DRIVERS.get(driver)
            if over is None:
                raise DeclarationError(
                    f"{cls.__qualname__} works through the {driver!r} driver, and no "
                    f"`@driver({driver!r})` is registered above it"
                )
            if name in vars(over):
                raise DeclarationError(
                    f"the {driver!r} driver already has a {name!r}, so the {registered!r} system "
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


def resolver_wants(resolver: Callable[..., Any]) -> dict[str, Any]:
    """What a resolver function asks for, by parameter name and annotation.

    The one place a type annotation decides what to build, and it is a function signature.
    """
    import inspect

    try:
        signature = inspect.signature(resolver)
    except (TypeError, ValueError):
        return {}
    hints: dict[str, Any] = {}
    try:
        hints = typing.get_type_hints(resolver)
    except Exception:  # noqa: BLE001 - an unresolvable annotation asks for nothing
        hints = {}
    return {
        name: hints.get(name, parameter.annotation)
        for name, parameter in signature.parameters.items()
        if parameter.kind
        not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    }
