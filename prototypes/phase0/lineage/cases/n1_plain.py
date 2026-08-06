"""No `from __future__ import annotations`. The annotation is the class itself, not a string."""

from ..declare import sqlite


@sqlite(table="owners", unique_by="email")
class Owner:
    email: str


@sqlite(table="lists", unique_by="slug")
class TodoList:
    owner: Owner
    slug: str
