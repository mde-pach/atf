"""A minimal stand-in for ATF's declaration layer, enough to ask §1.1 honestly.

`@adapter("sqlite")` mints an `@sqlite(...)` decorator, exactly as
`docs-next/reference/arrange.md#adapter` specifies. The decorator records the class and, so the
prototype can compare *when* resolution happens, also attempts resolution there and then.
"""

from __future__ import annotations

import sys
import types
import typing
from dataclasses import dataclass, field
from typing import Any

# Every class a system decorator has seen, in declaration order. A suite's registry is a slice of
# this — the classes belonging to the modules listed under `resources:`.
DECLARED: list[type] = []

Registry = dict[str, list[type]]


def registry_for(modules: list[str]) -> Registry:
    """The kinds one suite declares, keyed by class name — which is `.kind` in the specification.

    A name with more than one class behind it is risk §7 of MIGRATION.md, made visible.
    """
    registry: Registry = {}
    for cls in DECLARED:
        if cls.__module__.rsplit(".", 1)[-1] in modules:
            registry.setdefault(cls.__name__, []).append(cls)
    return registry


def qualify(cls: type) -> str:
    """`module.Kind` — so that two classes both called `Owner` are told apart in the output."""
    return f"{cls.__module__.rsplit('.', 1)[-1]}.{cls.__name__}"


@dataclass
class Resolution:
    """What one strategy made of one class's annotations."""

    edges: dict[str, str] = field(default_factory=dict)  # field name -> qualified resource kind
    plain: list[str] = field(default_factory=list)  # fields that are not lineage
    unresolved: dict[str, str] = field(default_factory=dict)  # field name -> the error
    failed: str = ""  # set when the strategy gave up on the whole class

    @property
    def summary(self) -> str:
        if self.failed:
            return f"WHOLE-CLASS FAILURE: {self.failed}"
        edges = ", ".join(f"{k}->{v}" for k, v in self.edges.items()) or "-"
        out = f"edges[{edges}]"
        if self.unresolved:
            out += " unresolved[" + "; ".join(f"{k}: {v}" for k, v in self.unresolved.items()) + "]"
        return out


def _declare_init(self: Any, **values: Any) -> None:
    """Construction declares; it does not touch anything."""
    self.__dict__.update(values)


def adapter(system: str):
    """Return a system decorator, the way `@adapter("sqlite")` ships `@sqlite(...)`."""

    def system_decorator(**options: Any):
        def decorate(cls: type) -> type:
            cls.__atf_system__ = system
            cls.__atf_options__ = options
            cls.__init__ = _declare_init
            # The decorator runs while the module is still executing. Resolving here is the
            # earliest possible moment, and the prototype keeps the answer to compare against
            # resolving once the module has finished.
            cls.__atf_at_decoration__ = resolve_by_field(cls, {})
            DECLARED.append(cls)
            return cls

        return decorate

    return system_decorator


sqlite = adapter("sqlite")


def _namespaces(cls: type) -> tuple[dict[str, Any], dict[str, Any]]:
    module = sys.modules.get(cls.__module__)
    globalns = dict(vars(module)) if module else {}
    localns = dict(vars(cls))
    return globalns, localns


def _unwrap(value: Any) -> Any:
    """Strip `| None` / `Optional[...]` down to the one type that might be a resource."""
    origin = typing.get_origin(value)
    if origin is typing.Union or origin is types.UnionType:
        inner = [a for a in typing.get_args(value) if a is not type(None)]
        if len(inner) == 1:
            return inner[0]
    return value


def _own_annotations(cls: type) -> dict[str, Any]:
    """The class's own annotations, unevaluated, without inherited ones."""
    return dict(cls.__dict__.get("__annotations__", {}))


def _record(result: Resolution, name: str, value: Any) -> None:
    target = _unwrap(value)
    if isinstance(target, type) and getattr(target, "__atf_system__", None):
        result.edges[name] = qualify(target)
    else:
        result.plain.append(name)


# --- Strategy 1: whole-class, all-or-nothing -------------------------------------------------


def resolve_whole_class(cls: type, registry: Registry) -> Resolution:
    """`typing.get_type_hints(cls)` — one call, and one failure loses every edge on the class."""
    result = Resolution()
    globalns, localns = _namespaces(cls)
    try:
        hints = typing.get_type_hints(cls, globalns=globalns, localns=localns)
    except Exception as exc:  # noqa: BLE001 - the point is to see what escapes
        result.failed = f"{type(exc).__name__}: {exc}"
        return result
    for name in _own_annotations(cls):
        _record(result, name, hints.get(name))
    return result


# --- Strategy 2: field by field ----------------------------------------------------------------


def resolve_by_field(cls: type, registry: Registry) -> Resolution:
    """Evaluate each annotation alone, so one bad field costs only that field."""
    result = Resolution()
    globalns, localns = _namespaces(cls)
    for name, annotation in _own_annotations(cls).items():
        try:
            value = eval(annotation, globalns, localns) if isinstance(annotation, str) else annotation  # noqa: S307
        except Exception as exc:  # noqa: BLE001
            result.unresolved[name] = f"{type(exc).__name__}: {exc}"
            continue
        _record(result, name, value)
    return result


# --- Strategy 3: field by field, then the registry ---------------------------------------------


def resolve_with_registry(cls: type, registry: Registry) -> Resolution:
    """Field by field; when a name will not evaluate, ask whether a declared kind is called that.

    ATF knows every kind, because a system decorator saw each one. An annotation reading `Owner`
    that will not evaluate is very probably the resource named `Owner` — unless two of them are.
    """
    result = resolve_by_field(cls, registry)
    for name, error in list(result.unresolved.items()):
        annotation = str(_own_annotations(cls)[name])
        candidate = annotation.removesuffix(" | None").removeprefix("Optional[").removesuffix("]").strip()
        matches = registry.get(candidate, [])
        if len(matches) == 1:
            result.edges[name] = qualify(matches[0])
            del result.unresolved[name]
        elif len(matches) > 1:
            both = " and ".join(qualify(m) for m in matches)
            result.unresolved[name] = f"{error}; and the name '{candidate}' is claimed by {both}"
        else:
            result.unresolved[name] = f"{error}; no declared kind is called '{candidate}'"
    return result


def resolve_factory(cls: type) -> Resolution:
    """The dependencies a factory takes, which are typed exactly as fields are.

    `-> Self` is in the same annotation set, so whatever reads the parameters meets it.
    """
    result = Resolution()
    factory = cls.__dict__.get("factory")
    if factory is None:
        result.failed = "no factory"
        return result
    function = factory.__func__ if isinstance(factory, classmethod) else factory
    globalns, localns = _namespaces(cls)
    try:
        hints = typing.get_type_hints(function, globalns=globalns, localns=localns)
    except Exception as exc:  # noqa: BLE001
        result.failed = f"{type(exc).__name__}: {exc}"
        return result
    for name, value in hints.items():
        _record(result, name, value)
    return result


def resolve_with_registry_guessing(cls: type, registry: Registry) -> Resolution:
    """The same, but taking the first match instead of refusing an ambiguous name.

    Here so the report shows what the tempting shortcut actually costs, rather than asserting it.
    """
    result = resolve_by_field(cls, registry)
    for name in list(result.unresolved):
        annotation = str(_own_annotations(cls)[name])
        candidate = annotation.removesuffix(" | None").removeprefix("Optional[").removesuffix("]").strip()
        if matches := registry.get(candidate, []):
            result.edges[name] = qualify(matches[0])
            del result.unresolved[name]
    return result


def resolve_recommended(cls: type, registry: Registry) -> Resolution:
    """What the case results point to. Run once, after every `resources:` module has been imported.

    Four answers, and each one is decided rather than guessed:

    - the annotation evaluates          -> that class, whatever it was aliased to
    - it does not, and names no kind    -> not lineage; leave it alone
    - it does not, and names one kind   -> that kind
    - it does not, and names two        -> refuse, naming both

    The third line is the one that carries risk, and it is the line that rescues a `TYPE_CHECKING`
    import. The fourth is the only place an edge could have gone silently wrong, so it is the only
    place this raises.
    """
    result = resolve_by_field(cls, registry)
    for name in list(result.unresolved):
        annotation = str(_own_annotations(cls)[name])
        candidate = annotation.removesuffix(" | None").removeprefix("Optional[").removesuffix("]").strip()
        matches = registry.get(candidate, [])
        if len(matches) == 1:
            result.edges[name] = qualify(matches[0])
            del result.unresolved[name]
        elif not matches:
            # No declared kind answers to this name, so it cannot be a lineage edge — which is the
            # whole reason this is safe to pass over rather than to fail the suite on.
            result.plain.append(name)
            del result.unresolved[name]
        else:
            both = " and ".join(qualify(m) for m in matches)
            result.unresolved[name] = f"'{candidate}' is declared twice, by {both} — say which"
    return result


STRATEGIES = {
    "whole-class": resolve_whole_class,
    "by-field": resolve_by_field,
    "by-field+registry": resolve_with_registry,
    "registry, guessing": resolve_with_registry_guessing,
    "RECOMMENDED": resolve_recommended,
}
