"""A `TYPE_CHECKING` import without the future import: Python itself refuses, at import."""

from typing import TYPE_CHECKING

from ..declare import sqlite

if TYPE_CHECKING:
    from .parents import Owner


@sqlite(table="lists", unique_by="slug")
class TodoList:
    owner: Owner  # noqa: F821 - the point of the case
    slug: str
