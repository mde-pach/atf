"""The canonical domain from DESIGN.md §5, declared through the same layer `lineage/` settled on.

Nothing here is annotated. `depends_on` is the graph; the constructor arguments are the shape.
"""

from __future__ import annotations

from typing import Self

from lineage.explicit import sqlite


@sqlite(table="owners", unique_by="email")
class Owner:
    @classmethod
    def factory(cls) -> Self:
        return cls(email="factory-built@example.com")


@sqlite(table="lists", unique_by="slug", depends_on=[Owner])
class TodoList:
    @classmethod
    def factory(cls, owner: Owner) -> Self:
        """Its parameter is named after the kind it needs, which is what `depends_on` says it is."""
        return cls(owner=owner, slug="factory-built")


@sqlite(table="reports", unique_by="slug", depends_on=[Owner])
class Report:
    """Needs an owner, and has no field to hold one — the shape a typed field could not state."""

    @classmethod
    def factory(cls, owner: Owner) -> Self:
        return cls(slug="factory-built", depends_on=[owner])


@sqlite(table="plans", unique_by="code", when_absent="require")
class Plan:
    """Declared with no factory, so asking for one by kind with nothing in scope is an error."""


primary = Owner(email="primary@example.com")
secondary = Owner(email="secondary@example.com")
groceries = TodoList(owner=primary, slug="groceries")
weekly = TodoList(owner=secondary, slug="weekly")
quarterly = Report(slug="quarterly", depends_on=[primary])
free = Plan(code="free")
