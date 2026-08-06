"""The ordinary case: the parent is declared above the child, in one module."""

from __future__ import annotations

from ..declare import sqlite


@sqlite(table="owners", unique_by="email")
class Owner:
    email: str


@sqlite(table="lists", unique_by="slug")
class TodoList:
    owner: Owner
    slug: str


primary = Owner(email="primary@example.com")
groceries = TodoList(owner=primary, slug="groceries")
