"""The worked example of an adapter, living in the suite that uses it.

`sqlite` is not part of ATF. ATF ships `command`, `browser`, `filesystem` and `process` — the
systems it needs to test itself — and nothing that binds it to one database. A decorator imported
from your own suite is the normal case.

`@adapter("sqlite")` ships `@sqlite(...)` with it, which is why the line below is the whole of what
`resources.py` needs to import.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, TypedDict

from atf import Unreachable, adapter, declaration_of, values_of

Record = dict[str, Any]


@adapter("sqlite")
class Sqlite:
    """Rows in a table, recognised by one column."""

    class Options(TypedDict):
        """What the decorator takes, per resource."""

        table: str

    class Settings(TypedDict):
        """What an environment configures."""

        path: str

    def __init__(self, settings: Settings) -> None:
        path = Path(settings["path"])
        try:
            self.db = sqlite3.connect(path)
        except sqlite3.Error as exc:
            raise Unreachable(f"cannot open {path}: {exc}") from exc
        self.db.row_factory = sqlite3.Row

    def _table(self, resource: Any) -> str:
        """The table this kind maps to. Named on the decorator, defaulting to the class's name."""
        declaration = declaration_of(resource)
        return declaration.options.get("table") or declaration.kind.lower()

    def _identity(self, resource: Any) -> Record:
        """The recognised fields and their values — what `find` looks a resource up by.

        Every one of them is there: ATF refuses a declaration whose `unique_by` names a field the
        resource does not carry, so this never has to guess with a partial key.
        """
        values = values_of(resource)
        return {field: values[field] for field in declaration_of(resource).unique_by}

    def find(self, resource: Any) -> Record | None:
        identity = self._identity(resource)
        where = " AND ".join(f"{column} = ?" for column in identity)
        try:
            row = self.db.execute(
                f"SELECT * FROM {self._table(resource)} WHERE {where}",  # noqa: S608 - names come from the declaration
                tuple(identity.values()),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            raise Unreachable(f"{self._table(resource)}: {exc}") from exc
        return dict(row) if row else None

    def create(self, resource: Any) -> Record:
        columns = self._columns(resource)
        names = ", ".join(columns)
        marks = ", ".join("?" for _ in columns)
        self.db.execute(
            f"INSERT INTO {self._table(resource)} ({names}) VALUES ({marks})",  # noqa: S608
            tuple(columns.values()),
        )
        self.db.commit()
        found = self.find(resource)
        if found is None:
            raise Unreachable(f"{self._table(resource)}: the row was written and cannot be read back")
        return found

    def update(self, resource: Any, found: Record, changes: Record) -> Record:
        assignments = ", ".join(f"{column} = ?" for column in changes)
        self.db.execute(
            f"UPDATE {self._table(resource)} SET {assignments} WHERE id = ?",  # noqa: S608
            (*changes.values(), found["id"]),
        )
        self.db.commit()
        return {**found, **changes}

    def delete(self, resource: Any, found: Record) -> None:
        self.db.execute(f"DELETE FROM {self._table(resource)} WHERE id = ?", (found["id"],))  # noqa: S608
        self.db.commit()

    def _columns(self, resource: Any) -> Record:
        """The declared fields, with a parent resolved to the id of the row it was made as."""
        columns: Record = {}
        for field, value in values_of(resource).items():
            if hasattr(type(value), "__atf_declaration__"):
                parent = self.find(value)
                if parent is None:
                    raise Unreachable(f"{field}: the parent it points at has not been made")
                columns[f"{field}_id"] = parent["id"]
            else:
                columns[field] = value
        return columns
