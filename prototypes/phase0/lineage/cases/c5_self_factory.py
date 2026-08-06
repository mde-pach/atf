"""A factory typed `-> Self`, whose parameters are themselves the dependencies.

`docs-next/reference/arrange.md#factory` types the return `Self`, so resolving a factory's
signature has to survive it.
"""

from __future__ import annotations

from typing import Self

from ..declare import sqlite


@sqlite(table="owners", unique_by="email")
class Owner:
    email: str

    @classmethod
    def factory(cls) -> Self:
        return cls(email="generated@example.com")


@sqlite(table="lists", unique_by="slug")
class TodoList:
    owner: Owner
    slug: str

    @classmethod
    def factory(cls, owner: Owner) -> Self:
        return cls(owner=owner, slug="generated")
