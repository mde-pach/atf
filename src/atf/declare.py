"""`Resource`, `Key`, `needs()`, `Driver`, and what a declaration records: `owner`, `lives`, `needs`."""

from __future__ import annotations

import re
import typing
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Annotated, Any, ClassVar, Generic, TypeVar

from .spi import REQUIRED, SpiError

#: Who is responsible for a thing existing. `atf` may make it; `them` means ATF only looks.
OWNERS = ("atf", "them")

#: The three spans a resource can live for, longest first. Nobody picks one — it is read off the
#: suite — but `lives=` overrides the reading for what ATF cannot see.
FOREVER, THE_RUN, THE_TEST = "forever", "the run", "the test"
SPANS = (FOREVER, THE_RUN, THE_TEST)

#: What every declared class carries, whatever a suite writes: the four methods, and `meta`, where
#: everything else ATF itself knows about the thing lives. A suite field of one of these names
#: would shadow something the framework needs, so it is refused at declaration time. See
#: `ResourceMeta` for what lives under `meta`.
RESERVED = ("find", "create", "update", "delete", "meta")


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
    """Every annotation on this class, with string annotations resolved, `Key`'s metadata included.

    A suite module may say `from __future__ import annotations`, so every annotation may be a string.
    """
    try:
        return typing.get_type_hints(cls, include_extras=True)
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


# --- Key: identity, said once, on the field ---------------------------------------------------------


class _KeyTag:
    """Sentinel carried inside `Annotated[...]`: marks an annotation as (part of) the identity."""


_T = TypeVar("_T")


def _is_key(hint: Any) -> bool:
    return typing.get_origin(hint) is Annotated and _KeyTag in typing.get_args(hint)[1:]


def key_fields(cls: type) -> tuple[str, ...]:
    """Every field this class marked `Key`, in annotation order — one column, or a composite."""
    hints = _hints(cls)
    return tuple(name for name in _declared_fields(cls) if _is_key(hints.get(name)))


# --- Declaration and Instance: what ATF records about a kind, and about one thing of it -----------


@dataclass(frozen=True)
class Declaration:
    """What a class recorded about itself on subclassing. Everything here belongs to ATF."""

    kind: str
    system: str
    #: How each unfilled field is filled — lineage and value generation, in one place.
    needs: dict[str, Need] = field(default_factory=dict)
    #: The fields marked `Key`, in order. What tells one of these apart.
    key: tuple[str, ...] = ()
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


def is_declared(cls: Any) -> bool:
    """Whether this exact class carries its own declaration — not merely inherits one."""
    return isinstance(cls, type) and "__atf_declaration__" in vars(cls)


# --- Driver access: `cls.http`, `self.sql` — the current run's driver, by name ---------------------


_CURRENT_GROUND: ContextVar[Any] = ContextVar("atf_ground", default=None)


@contextmanager
def activate(ground: Any) -> typing.Iterator[None]:
    """Make `ground` the one `DriverProperty` reads for as long as this block runs.

    `build_ground` calls `_CURRENT_GROUND.set(...)` directly for the ordinary case: one ground per
    process, alive for its whole life. This is for a tool holding two grounds live in one process
    at once.
    """
    token = _CURRENT_GROUND.set(ground)
    try:
        yield
    finally:
        _CURRENT_GROUND.reset(token)


class GroundNotActive(Exception):
    """Raised when a driver is read off a class with no environment built yet."""


_D = TypeVar("_D")


class DriverProperty(Generic[_D]):
    """`cls.http` / `self.sql` — the current run's driver instance, read off the active `Ground`.

    A system base class declares its own, by the name `build_ground` builds that driver under:
    `class Record(Resource): http: ClassVar[Http] = DriverProperty[Http]("http")`. Generic purely
    so a type checker knows `cls.http` reads as `Http`, not as `DriverProperty` itself.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def __set_name__(self, owner: type, attr: str) -> None:
        self.attr = attr

    def __get__(self, obj: Any, owner: type) -> _D:
        ground = _CURRENT_GROUND.get()
        if ground is None:
            raise GroundNotActive(
                f"{owner.__name__}.{self.attr} was read with no environment built yet"
            )
        try:
            return ground.drivers[self.name]
        except KeyError:
            raise GroundNotActive(
                f"the {self.name!r} driver has no settings in the {ground.config.name!r} "
                f"environment, and {owner.__name__} needs it"
            ) from None


def _driver_properties(cls: type) -> dict[str, DriverProperty]:
    """Every `DriverProperty` this class (or an ancestor, short of `Resource`) declares, by name."""
    found: dict[str, DriverProperty] = {}
    for ancestor in reversed(cls.__mro__):
        if ancestor is Resource or ancestor is object:
            continue
        for attr, value in vars(ancestor).items():
            if isinstance(value, DriverProperty):
                found[attr] = value
    return found


def drivers_wanted(cls: type) -> tuple[str, ...]:
    """The drivers a class asks for, read off the `DriverProperty` attributes it carries."""
    return tuple(dict.fromkeys(one.name for one in _driver_properties(cls).values()))


# --- Resource: the declared class itself, in the hierarchy, not beside it -------------------------


def snake(name: str) -> str:
    """`TodoList` becomes `todo_list` — a class's name, as the rest of a suite says it."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _written_at(cls: type) -> tuple[str, str]:
    return cls.__module__, cls.__qualname__


def _declared_fields(cls: type) -> dict[str, Any]:
    """The shape: every field this class annotates, and every one it inherits — short of `Resource`.

    A base class holding what several kinds share contributes its annotations to all of them. A
    `ClassVar` (a driver handle, or a system's own class-level setting) is never a suite's field.
    """
    found: dict[str, Any] = {}
    for ancestor in reversed(cls.__mro__):
        if ancestor is Resource or ancestor is object:
            continue
        found.update(vars(ancestor).get("__annotations__", {}))
    hints = _hints(cls)
    return {
        name: annotation
        for name, annotation in found.items()
        if typing.get_origin(hints.get(name, annotation)) is not ClassVar
    }


def _reject_reserved_names(cls: type, fields: dict[str, Any]) -> None:
    """A suite field cannot shadow a name the framework itself needs on every declared class."""
    reserved = set(RESERVED) | set(_driver_properties(cls))
    collide = sorted(set(fields) & reserved)
    if collide:
        raise DeclarationError(
            f"{cls.__name__} declares {', '.join(collide)}, which "
            f"{'is' if len(collide) == 1 else 'are'} reserved: every declared class carries its "
            f"own find/create/update/delete, its own meta (see Resource.meta), and whatever "
            f"driver its system needs."
        )


def _resource_init(self: Any, **values: Any) -> None:
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


def _resource_repr(self: Any) -> str:
    record = instance_of(self)
    return f"{record.name}:{record.kind}" if record.name else f"{record.kind}(unnamed)"


class ResourceMeta:
    """`self.meta` — everything ATF itself knows about a declared thing.

    Held apart from the suite's own fields, under one name: a suite field called `key` or `body` is
    entirely plausible — a license key, a request body — in a way `find`/`create` rarely are, and
    only the four verbs are reserved bare. A per-system setting such as a URL path or a table name
    is a different kind of thing — that system's own business, not ATF's — so it is a plain
    `ClassVar` the system's own base class declares, not part of this.
    """

    __slots__ = ("_resource",)

    def __init__(self, resource: Any) -> None:
        self._resource = resource

    @property
    def key(self) -> Any:
        """This resource's identity: the `Key`-marked field's value, or a dict for a composite key."""
        fields = declaration_of(self._resource).key
        if not fields:
            raise DeclarationError(f"{type(self._resource).__name__} declares no Key field")
        values = {name: getattr(self._resource, name) for name in fields}
        return values[fields[0]] if len(fields) == 1 else values

    @property
    def body(self) -> dict[str, Any]:
        """The declared fields a system writes.

        Scalars as given; a parent flattened to what it was last found or made as — never to its
        declared `Key`, which a database-assigned id may not even be. See
        `reconcile._remember_identity`, which is what fills that in.
        """
        return {
            name: instance_of(value).identity if is_resource(value) else value
            for name, value in instance_of(self._resource).values.items()
        }


class Resource:
    """One declared thing: a suite class subclasses this and *is* the resource.

    Nothing is assembled beside it, and nothing is handed to a system but this.
    `class Owner(Record, at="/owners")` runs `Resource.__init_subclass__` through `Record`'s own
    hook, which fixes what system this is and passes the rest up: fields, `needs()`, `Key` fields
    and the reserved-name check are all this base class's job, whatever system sits above it.
    """

    #: Fixed by a system's own base class, in its own `__init_subclass__` — never written directly.
    __atf_system__: ClassVar[str] = ""

    #: `Record.Key[str]` on a field marks it as (part of) this kind's identity — one mechanism,
    #: everywhere a resource has one: `Owner.email: Record.Key[str]`, `Task.slug: Row.Key[str]`. A
    #: composite key is more than one field marked this way. A plain generic alias, not a class with
    #: its own `__class_getitem__`: a type checker resolves this exactly as `str` (`Annotated`'s
    #: usual transparency), where it would not follow a custom subscript through to the same answer.
    Key = Annotated[_T, _KeyTag]

    def __init_subclass__(
        cls,
        *,
        owner: str = "atf",
        lives: str = "",
        system: str = "",
        **rest: Any,
    ) -> None:
        super().__init_subclass__(**rest)
        if system:
            # A system's own base class binds itself here, once: `class Record(Resource,
            # system="rest.record")`. It is never a suite author's business to write this kwarg.
            cls.__atf_system__ = system
        if not cls.__atf_system__:
            # Neither this class nor anything it inherits from is bound to a system yet — a base a
            # system is still building (`Under`, with no `system=` of its own), not a declared kind.
            return
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
        if "__init__" in vars(cls):
            raise DeclarationError(
                f"{cls.__name__} writes its own `__init__`. Construction is ATF's: a declared class "
                f"takes its fields as keyword arguments, and nothing else."
            )
        fields = _declared_fields(cls)
        _reject_reserved_names(cls, fields)
        cls.__atf_declaration__ = Declaration(
            kind=cls.__name__,
            system=cls.__atf_system__,
            needs=_read_needs(cls, fields),
            key=key_fields(cls),
            owner=owner,
            lives=lives,
            module=cls.__module__,
            fields=fields,
        )
        cls.__init__ = _resource_init
        cls.__repr__ = _resource_repr

    @property
    def meta(self) -> ResourceMeta:
        """Everything ATF itself knows about this declared thing, held apart from its own fields."""
        return ResourceMeta(self)

    def __getattr__(self, name: str) -> Any:
        """A declared field nobody gave, and resolution has not filled in yet, reads as `None`.

        Only fires for a name ordinary lookup missed — a name that is not one of the kind's own
        fields already failed at construction, in `_check_declared`. Provisioning outside a
        scenario (`atf plan --apply`) never runs resolution first, so a system reading a `needs()`
        field it expects to be there gets this, not a raw `AttributeError`.
        """
        if name in declaration_of(self).fields:
            return None
        raise AttributeError(name)

    # --- What ATF asks a resource -----------------------------------------------------------------
    #
    # All four read `self` — most only ever need `self.meta.key`, which is where the shape stays
    # simple (`return self.http.get(self.at, params=self.meta.key)`), but a thing like a tree
    # of files, whose `find` has to check the very fields it declared, or a process, whose `find`
    # reads a field that is not its identity, genuinely needs the rest of itself too. A system
    # writes these on its own base class; a record with a quirk overrides one directly, next to its
    # own declaration.

    def find(self) -> dict[str, Any] | None:
        """The record this thing is here, or `None` where there is none.

        Raise `Unreachable` where the question could not be asked at all; that is held apart from
        absence, so a service that is down never reads as a service with nothing in it.
        """
        raise NotImplementedError

    def create(self) -> dict[str, Any]:
        """Make one, and answer with the record that was written."""
        raise NotImplementedError

    def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Write these fields onto the one that is there, and answer with it."""
        raise NotImplementedError

    def delete(self) -> None:
        """Take it away. Called again on a record already gone, this stays quiet."""
        raise NotImplementedError

    # Four more are read off the class where it writes them, and each one buys something:
    #
    #   browse(self)                 -> list[Payload]        `Then there are 2 todo_lists`
    #   find_many(cls, resources)    -> list[Payload | None] one round trip about several
    #   check(self)                  -> str                  refuse a declaration before a run
    #   begin() / rollback()        -> None                 a transaction around one test
    #   capture(self)                -> list[str]             artefacts to keep when a test fails
    #   describe()                  -> list[dict]            what this system holds
    #   close()                     -> None                  let go of what was held open


def offers(cls: type, method: str) -> bool:
    """Whether this class wrote one of the methods itself, past whatever `Resource` declares.

    Which methods a system wrote decides what ATF may do with its things and which sentences exist.
    """
    own = getattr(cls, method, None)
    return callable(own) and own is not getattr(Resource, method, None)


def check_shape(name: str, cls: type) -> None:
    """Whether this class is a resource system at all, before an environment is built from it."""
    missing = [method for method in REQUIRED if not offers(cls, method)]
    if missing:
        raise SpiError(
            f"the {name!r} system ({cls.__module__}.{cls.__qualname__}) has no "
            f"{', '.join(missing)} — a system writes all of {', '.join(REQUIRED)}"
        )


# --- Driver: the machinery a system works through ---------------------------------------------------

ADAPTERS: dict[str, type] = {}
DRIVERS: dict[str, type] = {}


class Driver:
    """The machinery a system works through: a connection, a client, a browser, a shell.

    Subclassing registers it under its own class name — `class Sql(Driver)` is `sql` — and one is
    built per environment from the `atf.yaml` block of that name, which arrives as `settings`. A
    nested `Settings` typed dict says what that block may hold, and the manifest is checked on it.
    """

    #: What this driver is registered as, taken from the class name.
    __atf_driver__: ClassVar[str] = ""

    def __init_subclass__(cls, **rest: Any) -> None:
        super().__init_subclass__(**rest)
        name = snake(cls.__name__)
        seen = DRIVERS.get(name)
        if seen is not None and _written_at(seen) != _written_at(cls):
            raise DeclarationError(
                f"two drivers are called {name!r}: {seen.__module__}.{seen.__qualname__} "
                f"and {cls.__module__}.{cls.__qualname__} — a driver is named by its class"
            )
        DRIVERS[name] = cls
        cls.__atf_driver__ = name


def register_system(cls: type[Resource], driver: type, name: str = "") -> str:
    """Register a system's own base class as `<driver>.<name>`, and bind it to that name.

    Called once, right after the class body, by the system module that owns it — never by a suite:
    `class Page(Resource): ...` then `register_system(Page, Browser, "page")`. `Page` itself stays
    undeclared (nothing sets `system=` in its own class statement), and every suite subclass of it
    inherits `__atf_system__` the ordinary way, through the MRO. Compared by where it is written, so
    re-importing one file is a reload and not a clash.
    """
    if not (isinstance(driver, type) and issubclass(driver, Driver)):
        raise DeclarationError(
            f"{cls.__qualname__} names {driver!r} as its driver, and a driver is a class "
            f"subclassing `Driver`"
        )
    registered = f"{driver.__atf_driver__}.{name or snake(cls.__name__)}"
    seen = ADAPTERS.get(registered)
    if seen is not None and _written_at(seen) != _written_at(cls):
        raise DeclarationError(
            f"two systems are registered as {registered!r}: "
            f"{seen.__module__}.{seen.__qualname__} and {cls.__module__}.{cls.__qualname__}"
        )
    ADAPTERS[registered] = cls
    cls.__atf_system__ = registered
    return registered


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
