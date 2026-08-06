"""The parent is imported under `TYPE_CHECKING`, so the name does not exist at runtime.

A type checker is happy, the editor resolves it, and nothing at runtime can evaluate it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..declare import sqlite

if TYPE_CHECKING:
    from .parents import Owner


@sqlite(table="lists", unique_by="slug")
class TodoList:
    owner: Owner
    slug: str
