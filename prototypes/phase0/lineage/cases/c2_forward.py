"""A forward reference: the child names a parent declared further down the module.

PEP 563 is what makes this legal to write, so a suite author will write it.
"""

from __future__ import annotations

from ..declare import sqlite


@sqlite(table="lists", unique_by="slug")
class TodoList:
    owner: Owner
    slug: str


@sqlite(table="owners", unique_by="email")
class Owner:
    email: str
