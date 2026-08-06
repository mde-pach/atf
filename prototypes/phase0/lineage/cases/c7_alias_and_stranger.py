"""Two things at once: a parent imported under an alias, and a field ATF has no business reading.

The alias is why resolving by *name* rather than by evaluation is not sound — the annotation says
`Boss`, and no declared kind is called that. The `stranger` field is the false-positive test: it is
not lineage, it will never evaluate, and a strategy that hard-errors on any unresolvable annotation
rejects a module that is perfectly correct.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..declare import sqlite
from .parents import Owner as Boss

if TYPE_CHECKING:
    from decimal import Decimal


@sqlite(table="lists", unique_by="slug")
class TodoList:
    owner: Boss
    slug: str
    balance: Decimal
