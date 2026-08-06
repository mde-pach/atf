"""The parent is imported normally from another module."""

from __future__ import annotations

from ..declare import sqlite
from .parents import Owner


@sqlite(table="lists", unique_by="slug")
class TodoList:
    owner: Owner
    slug: str
