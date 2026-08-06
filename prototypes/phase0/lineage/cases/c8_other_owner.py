"""A second module declaring a kind that is also called `Owner`, against a different table."""

from __future__ import annotations

from ..declare import sqlite


@sqlite(table="tenant_owners", unique_by="email")
class Owner:
    email: str
    tenant: str
