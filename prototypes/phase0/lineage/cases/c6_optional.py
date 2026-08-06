"""An optional parent — the shape a suite reaches for when a list may have no owner."""

from __future__ import annotations

from typing import Optional

from ..declare import sqlite


@sqlite(table="owners", unique_by="email")
class Owner:
    email: str


@sqlite(table="lists", unique_by="slug")
class TodoList:
    owner: Owner | None
    slug: str


@sqlite(table="archives", unique_by="slug")
class Archive:
    owner: Optional[Owner]  # noqa: UP045 - the older spelling, which suites still contain
    slug: str
