"""What depends on what, read off `depends_on`. No adapter is called and nothing is asked."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from typing_extensions import override

from .declare import Declaration, declaration_of, instance_of, is_resource, name_of


class CycleError(Exception):
    """Raised when a resource needs itself, however long the way round."""


@dataclass(frozen=True)
class Unmet:
    """A kind a resource needs that nothing named, and what can be done about it."""

    kind: type
    needed_by: object

    @property
    def has_factory(self) -> bool:
        return hasattr(self.kind, "factory")

    @override
    def __str__(self) -> str:
        needed_by = name_of(self.needed_by) or declaration_of(self.needed_by).kind
        if self.has_factory:
            return f"{needed_by} needs a {self.kind.__name__}, which its factory can build"
        return (
            f"{needed_by} needs a {self.kind.__name__}, none is named, "
            f"and {self.kind.__name__} has no factory — name the one you mean"
        )


def _declared_parents(node: object) -> list[object]:
    """The resources this one names, whether as a value or in `depends_on`."""
    return [entry for entry in instance_of(node).depends_on if is_resource(entry)]


def unmet(node: object) -> list[Unmet]:
    """The kinds this resource needs that nothing supplied.

    A kind is answered by anything already supplied of that kind, so `depends_on=[Owner]` on the
    class and `owner=primary` on the instance are one edge.
    """
    supplied = _declared_parents(node)
    named_on_the_instance = [e for e in instance_of(node).depends_on if isinstance(e, type)]
    wanted = dict.fromkeys((*declaration_of(node).kinds_needed, *named_on_the_instance))
    return [
        Unmet(kind=kind, needed_by=node)
        for kind in wanted
        if not any(type(parent) is kind for parent in supplied)
    ]


def parents(node: object) -> list[object]:
    """Everything this resource needs that a suite actually named, in declaration order."""
    return _unique(_declared_parents(node))


def _unique(nodes: list[object]) -> list[object]:
    """Preserve order, drop repeats, compare by identity — a graph node is an identity."""
    out: list[object] = []
    for node in nodes:
        if not any(seen is node for seen in out):
            out.append(node)
    return out


def closure(node: object) -> list[object]:
    """Everything that must exist before this one, parents first, each appearing once.

    This is the order things are made in, and the reverse of the order they are torn down in, so a
    list is deleted before its owner.
    """
    ordered: list[object] = []
    seen: list[object] = []

    def visit(current: object, trail: tuple[object, ...]) -> None:
        if any(step is current for step in trail):
            start = next(i for i, step in enumerate(trail) if step is current)
            way_round = [*trail[start:], current]
            raise CycleError("a resource cannot need itself: " + " -> ".join(repr(step) for step in way_round))
        if any(step is current for step in seen):
            return
        for parent in parents(current):
            visit(parent, (*trail, current))
        seen.append(current)
        ordered.append(current)

    visit(node, ())
    return ordered


def order(nodes: Iterable[object]) -> list[object]:
    """Every one of these and everything they need, in the order they are made."""
    ordered: list[object] = []
    for node in nodes:
        for step in closure(node):
            if not any(seen is step for seen in ordered):
                ordered.append(step)
    return ordered


def teardown_order(nodes: Iterable[object]) -> list[object]:
    """The reverse of [order](#order) — always reverse lineage, so a parent goes last."""
    return list(reversed(order(nodes)))


def dependents(node: object, among: Iterable[object]) -> list[object]:
    """What breaks if this one changes — `atf impact`."""
    return [
        other
        for other in among
        if other is not node and any(step is node for step in closure(other)[:-1])
    ]


def unused(among: Iterable[object]) -> list[object]:
    """What nothing else asks for — `atf unused`, before tests are taken into account."""
    everything = list(among)
    needed: list[object] = []
    for node in everything:
        for step in closure(node)[:-1]:
            needed.append(step)
    return [node for node in everything if not any(step is node for step in needed)]


def edges(among: Iterable[object]) -> list[tuple[object, object]]:
    """Every (child, parent) pair, which is the whole graph as data for the editor and for agents."""
    return [(node, parent) for node in among for parent in parents(node)]


def declarations(among: Iterable[object]) -> dict[str, Declaration]:
    """The kinds these resources belong to, keyed by kind name."""
    return {declaration_of(node).kind: declaration_of(node) for node in among}
