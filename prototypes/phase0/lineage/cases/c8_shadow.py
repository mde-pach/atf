"""Risk §7, sharpened: the annotation will not evaluate, and two kinds answer to the name.

The author means `c8_other_owner.Owner` — a type checker agrees, because that is what the
`TYPE_CHECKING` import says. At runtime the name is a string and `parents.Owner` is equally called
`Owner`. Resolving by name has to pick, and picking is guessing at which table to write to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..declare import sqlite

if TYPE_CHECKING:
    from .c8_other_owner import Owner


@sqlite(table="tenant_lists", unique_by="slug")
class TodoList:
    owner: Owner
    slug: str
