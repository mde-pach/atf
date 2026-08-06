"""A forward reference without the future import: Python itself refuses, at import."""

from ..declare import sqlite


@sqlite(table="lists", unique_by="slug")
class TodoList:
    owner: Owner  # noqa: F821 - the point of the case
    slug: str


@sqlite(table="owners", unique_by="email")
class Owner:
    email: str
