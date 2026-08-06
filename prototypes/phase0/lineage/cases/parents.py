"""Resources declared in a module other than the one that depends on them."""

from __future__ import annotations

from ..declare import sqlite


@sqlite(table="owners", unique_by="email")
class Owner:
    email: str
