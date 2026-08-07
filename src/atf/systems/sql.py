"""`@sql(...)` — rows in a table, over any DB-API driver named by the environment's URL."""

from __future__ import annotations

import importlib
from typing import Any, TypedDict
from urllib.parse import urlparse

from ..declare import Unreachable, adapter, declaration_of, is_resource, values_of
from ..spi import Record

#: URL scheme to the DB-API module that answers it, and the placeholder that module wants.
DRIVERS: dict[str, tuple[str, str]] = {
    "sqlite": ("sqlite3", "?"),
    "postgresql": ("psycopg", "%s"),
    "postgres": ("psycopg", "%s"),
    "mysql": ("pymysql", "%s"),
}


def _table(
    name: str,
    columns: list[tuple[str, str]],
    keys: list[str],
    unique: list[str],
    parents: dict[str, str],
) -> dict[str, Any]:
    """One table, in the shape `atf adopt` reads."""
    return {
        "table": name,
        "columns": [{"name": one, "type": kind} for one, kind in columns],
        "key": keys[0] if len(keys) == 1 else "",
        "unique_by": unique[0] if unique else "",
        "parents": parents,
    }


@adapter("sql")
class Sql:
    """Rows in a table, recognised by the columns `unique_by` names."""

    class Options(TypedDict, total=False):
        """What the decorator takes, per resource."""

        #: The table this kind maps to. Defaults to the class's name, lowercased.
        table: str
        #: What this schema calls the primary key.
        id_field: str
        #: What a column holding a parent is called: `owner` becomes `owner_id`.
        parent_suffix: str

    class Settings(TypedDict, total=False):
        """What an environment configures. One of the two, never both."""

        #: A database file, resolved against the manifest: `path: ./todo.db`.
        path: str
        #: A database somewhere else: `postgresql://user:pass@host/db`, `mysql://…`.
        url: str

    def __init__(self, settings: Settings) -> None:
        path, url = str(settings.get("path", "")), str(settings.get("url", ""))
        if bool(path) == bool(url):
            raise ValueError("the sql system takes a `path` to a database file, or a `url` to one elsewhere")
        self.path, self.url = path, url
        scheme = "sqlite" if path else urlparse(url).scheme.split("+")[0]
        known = DRIVERS.get(scheme)
        if known is None:
            raise ValueError(f"no driver for {scheme!r} (known: {', '.join(sorted(DRIVERS))})")
        self.module_name, self.mark = known
        self._connection: Any = None
        self._open = False

    @property
    def where(self) -> str:
        """What this adapter is pointed at, for a message about not reaching it."""
        return self.path or self.url

    # --- The connection ---------------------------------------------------------------------------

    @property
    def db(self) -> Any:
        """The connection, opened on the first question asked of it."""
        if self._connection is not None:
            return self._connection
        try:
            driver = importlib.import_module(self.module_name)
        except ImportError as exc:
            raise Unreachable(f"the sql system needs {self.module_name} to reach {self.where}") from exc
        try:
            self._connection = self._connect(driver)
        except Exception as exc:  # noqa: BLE001 - a database that will not open is unreachable
            raise Unreachable(f"cannot open {self.where}: {exc}") from exc
        return self._connection

    def _connect(self, driver: Any) -> Any:
        if self.module_name != "sqlite3":
            return driver.connect(self.url)
        return driver.connect(self.path or ":memory:")

    def _rows(self, statement: str, values: tuple[Any, ...] = ()) -> list[Record]:
        cursor = self.db.cursor()
        try:
            cursor.execute(statement, values)
        except Exception as exc:  # noqa: BLE001 - a statement the schema refuses is unreachable
            raise Unreachable(f"{statement}: {exc}") from exc
        if cursor.description is None:
            return []
        columns = [one[0] for one in cursor.description]
        return [dict(zip(columns, tuple(row), strict=False)) for row in cursor.fetchall()]

    def _run(self, statement: str, values: tuple[Any, ...] = ()) -> None:
        cursor = self.db.cursor()
        try:
            cursor.execute(statement, values)
        except Exception as exc:  # noqa: BLE001
            raise Unreachable(f"{statement}: {exc}") from exc
        if not self._open:
            self.db.commit()

    def _marks(self, many: int) -> str:
        return ", ".join(self.mark for _ in range(many))

    # --- What a resource declared -----------------------------------------------------------------

    def _table(self, resource: Any) -> str:
        declaration = declaration_of(resource)
        return str(declaration.options.get("table") or declaration.kind.lower())

    def _id_field(self, resource: Any) -> str:
        return str(declaration_of(resource).options.get("id_field", "id"))

    def _suffix(self, resource: Any) -> str:
        return str(declaration_of(resource).options.get("parent_suffix", "_id"))

    def _identity(self, resource: Any) -> Record:
        values = values_of(resource)
        return {field: values[field] for field in declaration_of(resource).unique_by}

    def _columns(self, resource: Any) -> Record:
        """The declared fields, with a parent resolved to the key of the row it was made as."""
        columns: Record = {}
        for field, value in values_of(resource).items():
            if not is_resource(value):
                columns[field] = value
                continue
            parent = self.find(value)
            if parent is None:
                raise Unreachable(f"{field}: the parent it points at has not been made")
            columns[f"{field}{self._suffix(resource)}"] = parent[self._id_field(value)]
        return columns

    # --- The four ---------------------------------------------------------------------------------

    def find(self, resource: Any) -> Record | None:
        identity = self._identity(resource)
        if not identity:
            raise Unreachable(f"{declaration_of(resource).kind}: nothing to recognise it by")
        where = " AND ".join(f"{column} = {self.mark}" for column in identity)
        found = self._rows(
            f"SELECT * FROM {self._table(resource)} WHERE {where}",  # noqa: S608 - names come from the declaration
            tuple(identity.values()),
        )
        return found[0] if found else None

    def find_many(self, resources: list[Any]) -> dict[int, Record | None]:
        """Every one of these, one question per table, keyed by identity.

        Resources recognised by a single column are asked for with one `IN`. Anything recognised by
        several is asked for one at a time, which is what `find` already does.
        """
        out: dict[int, Record | None] = {}
        by_table: dict[str, list[Any]] = {}
        for node in resources:
            if len(declaration_of(node).unique_by) == 1:
                by_table.setdefault(self._table(node), []).append(node)
            else:
                out[id(node)] = self.find(node)

        for table, mine in by_table.items():
            column = declaration_of(mine[0]).unique_by[0]
            wanted = [self._identity(node)[column] for node in mine]
            rows = self._rows(
                f"SELECT * FROM {table} WHERE {column} IN ({self._marks(len(wanted))})",  # noqa: S608
                tuple(wanted),
            )
            by_value = {str(row.get(column)): row for row in rows}
            for node in mine:
                out[id(node)] = by_value.get(str(self._identity(node)[column]))
        return out

    def create(self, resource: Any) -> Record:
        columns = self._columns(resource)
        names = ", ".join(columns)
        self._run(
            f"INSERT INTO {self._table(resource)} ({names}) VALUES ({self._marks(len(columns))})",  # noqa: S608
            tuple(columns.values()),
        )
        found = self.find(resource)
        if found is None:
            raise Unreachable(f"{self._table(resource)}: the row was written and cannot be read back")
        return found

    def update(self, resource: Any, found: Record, changes: Record) -> Record:
        assignments = ", ".join(f"{column} = {self.mark}" for column in changes)
        key = self._id_field(resource)
        self._run(
            f"UPDATE {self._table(resource)} SET {assignments} WHERE {key} = {self.mark}",  # noqa: S608
            (*changes.values(), found[key]),
        )
        return {**found, **changes}

    def delete(self, resource: Any, found: Record) -> None:
        key = self._id_field(resource)
        self._run(
            f"DELETE FROM {self._table(resource)} WHERE {key} = {self.mark}",  # noqa: S608
            (found[key],),
        )

    # --- The optional ones ------------------------------------------------------------------------

    def act(self, resource: Any, found: Record, action: Any) -> Record:
        """A declared verb: write the fields the action names onto this row."""
        return self.update(resource, found, dict(getattr(action, "values", {})))

    def browse(self, resource: Any) -> list[Record]:
        """Every row of this kind."""
        return self._rows(f"SELECT * FROM {self._table(resource)}")  # noqa: S608

    def describe(self) -> list[dict[str, Any]]:
        """Every table this database holds, as the facts a declaration is written from.

        One entry per table: its name, its columns and their types, the single column that
        recognises a row, and the tables it points at.
        """
        if self.module_name == "sqlite3":
            return [self._describe_sqlite(name) for name in self._sqlite_tables()]
        return [self._describe_standard(name) for name in self._standard_tables()]

    # --- sqlite, through its pragmas --------------------------------------------------------------

    def _sqlite_tables(self) -> list[str]:
        rows = self._rows(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [str(row["name"]) for row in rows]

    def _describe_sqlite(self, table: str) -> dict[str, Any]:
        columns = self._rows(f"PRAGMA table_info({table})")
        keys = [str(one["name"]) for one in columns if one.get("pk")]
        parents = {
            str(one["from"]): str(one["table"])
            for one in self._rows(f"PRAGMA foreign_key_list({table})")
        }
        unique: list[str] = []
        for index in self._rows(f"PRAGMA index_list({table})"):
            if not index.get("unique"):
                continue
            named = [str(one["name"]) for one in self._rows(f"PRAGMA index_info({index['name']})")]
            if len(named) == 1 and named[0] not in keys:
                unique.append(named[0])
        return _table(table, [(str(one["name"]), str(one["type"])) for one in columns], keys, unique, parents)

    # --- everything else, through information_schema -----------------------------------------------

    def _standard_tables(self) -> list[str]:
        rows = self._rows(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'mysql', 'performance_schema') "
            "AND table_type = 'BASE TABLE' ORDER BY table_name"
        )
        return [str(row["table_name"]) for row in rows]

    def _describe_standard(self, table: str) -> dict[str, Any]:
        columns = self._rows(
            "SELECT column_name, data_type FROM information_schema.columns "
            f"WHERE table_name = {self.mark} ORDER BY ordinal_position",
            (table,),
        )
        constraints = self._rows(
            "SELECT tc.constraint_type, kcu.column_name, ccu.table_name AS points_at "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            "LEFT JOIN information_schema.constraint_column_usage ccu "
            "  ON tc.constraint_name = ccu.constraint_name "
            f"WHERE tc.table_name = {self.mark}",
            (table,),
        )
        keys = [str(one["column_name"]) for one in constraints if one["constraint_type"] == "PRIMARY KEY"]
        unique = [
            str(one["column_name"])
            for one in constraints
            if one["constraint_type"] == "UNIQUE" and str(one["column_name"]) not in keys
        ]
        parents = {
            str(one["column_name"]): str(one["points_at"])
            for one in constraints
            if one["constraint_type"] == "FOREIGN KEY" and one.get("points_at")
        }
        return _table(
            table, [(str(one["column_name"]), str(one["data_type"])) for one in columns], keys, unique, parents
        )

    def begin(self) -> None:
        """Open a transaction, so everything a test does can be undone in one statement."""
        if self._open:
            return
        self._run_raw("BEGIN")
        self._open = True

    def rollback(self) -> None:
        """Undo everything since `begin`."""
        if not self._open:
            return
        self._open = False
        try:
            self.db.rollback()
        except Exception as exc:  # noqa: BLE001
            raise Unreachable(f"the transaction could not be rolled back: {exc}") from exc

    def _run_raw(self, statement: str) -> None:
        try:
            self.db.cursor().execute(statement)
        except Exception:  # noqa: BLE001 - a driver already inside a transaction has nothing to open
            return
