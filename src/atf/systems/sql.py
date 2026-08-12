"""`@row(...)` — a row in a table, over the `sql` driver."""

from __future__ import annotations

import importlib
from typing import Any, TypedDict
from urllib.parse import urlparse

from ..declare import Unreachable, adapter, driver
from ..spi import Record, Resource

#: URL scheme to the DB-API module that answers it, and the placeholder that module wants.
MODULES: dict[str, tuple[str, str]] = {
    "sqlite": ("sqlite3", "?"),
    "postgresql": ("psycopg", "%s"),
    "postgres": ("psycopg", "%s"),
    "mysql": ("pymysql", "%s"),
}


def _table(
    name: str,
    columns: list[tuple[str, str]],
    keys: list[str],
    unique: list[tuple[str, ...]],
    parents: dict[str, str],
) -> dict[str, Any]:
    """One table, as the facts recognition and a written declaration are both read from."""
    return {
        "table": name,
        "columns": [{"name": one, "type": kind} for one, kind in columns],
        "key": keys[0] if len(keys) == 1 else "",
        #: Every unique constraint, shortest first. A row unique only in combination is one entry.
        "uniques": sorted(unique, key=len),
        "unique_by": unique[0][0] if unique and len(unique[0]) == 1 else "",
        "parents": parents,
    }


@driver("sql")
class Database:
    """One connection, over any DB-API module named by the environment's URL.

    A step asks for this by the name `sql`; the `sql` adapter works through it.
    """

    class Settings(TypedDict, total=False):
        """What an environment configures. One of the two, never both."""

        #: A database file, resolved against the manifest: `path: ./todo.db`.
        path: str
        #: A database somewhere else: `postgresql://user:pass@host/db`, `mysql://…`.
        url: str
        #: Wrap each test in a transaction and roll it back. Off unless stated: only a system under
        #: test running *inside* this process can see uncommitted rows, and a command line cannot.
        transactional: bool

    def __init__(self, settings: Settings) -> None:
        path, url = str(settings.get("path", "")), str(settings.get("url", ""))
        if bool(path) == bool(url):
            raise ValueError("the sql system takes a `path` to a database file, or a `url` to one elsewhere")
        self.path, self.url = path, url
        scheme = "sqlite" if path else urlparse(url).scheme.split("+")[0]
        known = MODULES.get(scheme)
        if known is None:
            raise ValueError(f"no driver for {scheme!r} (known: {', '.join(sorted(MODULES))})")
        self.module_name, self.mark = known
        self.transactional = bool(settings.get("transactional", False))
        self._connection: Any = None
        self._open = False
        self._schema: list[dict[str, Any]] | None = None

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
            module = importlib.import_module(self.module_name)
        except ImportError as exc:
            raise Unreachable(f"the sql system needs {self.module_name} to reach {self.where}") from exc
        try:
            self._connection = self._connect(module)
        except Exception as exc:
            raise Unreachable(f"cannot open {self.where}: {exc}") from exc
        return self._connection

    def _connect(self, module: Any) -> Any:
        if self.module_name != "sqlite3":
            return module.connect(self.url)
        return module.connect(self.path or ":memory:")

    def rows(self, statement: str, values: tuple[Any, ...] = ()) -> list[Record]:
        cursor = self.db.cursor()
        try:
            cursor.execute(statement, values)
        except Exception as exc:
            raise Unreachable(f"{statement}: {exc}") from exc
        if cursor.description is None:
            return []
        columns = [one[0] for one in cursor.description]
        return [dict(zip(columns, tuple(row), strict=False)) for row in cursor.fetchall()]

    def execute(self, statement: str, values: tuple[Any, ...] = ()) -> None:
        cursor = self.db.cursor()
        try:
            cursor.execute(statement, values)
        except Exception as exc:
            raise Unreachable(f"{statement}: {exc}") from exc
        if not self._open:
            self.db.commit()

    def marks(self, many: int) -> str:
        return ", ".join(self.mark for _ in range(many))

    def describe(self) -> list[dict[str, Any]]:
        """Every table this database holds, as the facts a declaration is written from.

        One entry per table: its name, its columns and their types, the single column that
        recognises a row, and the tables it points at.
        """
        if self.module_name == "sqlite3":
            return [self._describe_sqlite(name) for name in self._sqlite_tables()]
        return [self._describe_standard(name) for name in self._standard_tables()]

    def schema(self) -> list[dict[str, Any]]:
        """The same, read once and held. Recognition asks this per kind, and the answer is fixed."""
        if self._schema is None:
            self._schema = self.describe()
        return self._schema

    # --- sqlite, through its pragmas --------------------------------------------------------------

    def _sqlite_tables(self) -> list[str]:
        rows = self.rows(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [str(row["name"]) for row in rows]

    def _describe_sqlite(self, table: str) -> dict[str, Any]:
        columns = self.rows(f"PRAGMA table_info({table})")
        keys = [str(one["name"]) for one in columns if one.get("pk")]
        parents = {
            str(one["from"]): str(one["table"])
            for one in self.rows(f"PRAGMA foreign_key_list({table})")
        }
        unique: list[tuple[str, ...]] = []
        for index in self.rows(f"PRAGMA index_list({table})"):
            if not index.get("unique"):
                continue
            named = tuple(str(one["name"]) for one in self.rows(f"PRAGMA index_info({index['name']})"))
            if named and set(named) != set(keys):
                unique.append(named)
        return _table(table, [(str(one["name"]), str(one["type"])) for one in columns], keys, unique, parents)

    # --- everything else, through information_schema -----------------------------------------------

    def _standard_tables(self) -> list[str]:
        rows = self.rows(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'mysql', 'performance_schema') "
            "AND table_type = 'BASE TABLE' ORDER BY table_name"
        )
        return [str(row["table_name"]) for row in rows]

    def _describe_standard(self, table: str) -> dict[str, Any]:
        columns = self.rows(
            "SELECT column_name, data_type FROM information_schema.columns "
            f"WHERE table_name = {self.mark} ORDER BY ordinal_position",
            (table,),
        )
        constraints = self.rows(
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
        grouped: dict[str, list[str]] = {}
        for one in constraints:
            if one["constraint_type"] == "UNIQUE":
                grouped.setdefault(str(one.get("constraint_name", one["column_name"])), []).append(
                    str(one["column_name"])
                )
        unique = [tuple(columns) for columns in grouped.values() if set(columns) != set(keys)]
        parents = {
            str(one["column_name"]): str(one["points_at"])
            for one in constraints
            if one["constraint_type"] == "FOREIGN KEY" and one.get("points_at")
        }
        return _table(
            table, [(str(one["column_name"]), str(one["data_type"])) for one in columns], keys, unique, parents
        )

    def begin(self) -> None:
        """Open a transaction, so everything a test does can be undone in one statement.

        Does nothing unless the environment sets `transactional: true`.
        """
        if self._open or not self.transactional:
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
        except Exception as exc:
            raise Unreachable(f"the transaction could not be rolled back: {exc}") from exc

    def _run_raw(self, statement: str) -> None:
        try:
            self.db.cursor().execute(statement)
        except Exception:  # noqa: BLE001 - a driver already inside a transaction has nothing to open
            return


@adapter("row", driver="sql")
class Row:
    """One row in a table, recognised by whatever the table holds unique."""

    class Options(TypedDict, total=False):
        """What the decorator takes, per resource."""

        #: The table this kind maps to. Defaults to the class's name, lowercased.
        table: str
        #: What this schema calls the primary key.
        id_field: str
        #: What a column holding a parent is called: `owner` becomes `owner_id`.
        parent_suffix: str

    def __init__(self, sql: Database) -> None:
        self.sql = sql

    def table(self, resource: Resource) -> str:
        return str(resource.options.get("table") or resource.kind.lower())

    def recognises(self, resource: Resource) -> tuple[str, ...]:
        """What tells one row from another: **whatever the table holds unique**.

        The author writes nothing. Uniqueness is structure the schema already holds, and asking for
        it back would be asking somebody to restate what this system can look up.
        """
        table = self.table(resource)
        for one in self.sql.schema():
            if one["table"] != table:
                continue
            # Shortest first, so a single unique column beats a composite one that also fits.
            for columns in [*one["uniques"], (one["key"],) if one["key"] else ()]:
                if columns and all(column in resource.fields for column in columns):
                    return tuple(str(column) for column in columns)
            held = ", ".join(str(c["name"]) for c in one["columns"]) or "no columns"
            raise Unreachable(
                f"{table} holds nothing unique that {resource.kind} declares.\n"
                f"  The table has {held}, and a row is recognised by what the table holds unique."
            )
        raise Unreachable(f"{table}: no such table, so nothing recognises a {resource.kind}")

    def _id_field(self, resource: Resource) -> str:
        return str(resource.options.get("id_field", "id"))

    def _suffix(self, resource: Resource) -> str:
        return str(resource.options.get("parent_suffix", "_id"))

    # --- What a resource declared -----------------------------------------------------------------


    def _held(self, resource: Resource) -> set[str]:
        """Every column this table has, as the schema says."""
        table = self.table(resource)
        for one in self.sql.schema():
            if one["table"] == table:
                return {str(column["name"]) for column in one["columns"]}
        return set()

    def _columns(self, resource: Resource) -> Record:
        """The declared fields, and each parent as the key of the row it was made as.

        A parent the table has no column for is left out. Something can have to exist first and
        leave no trace in the row, and whether it does is a fact the schema holds.
        """
        columns: Record = dict(resource.values)
        suffix = self._suffix(resource)
        held = self._held(resource)
        for field, parent in resource.parents.items():
            key = f"{field}{suffix}"
            if held and key not in held:
                continue
            if parent.key is None:
                raise Unreachable(f"{field}: the parent it points at has not been made")
            columns[key] = parent.key
        return columns

    # --- The four ---------------------------------------------------------------------------------

    def find(self, resource: Resource) -> Record | None:
        identity = dict(resource.identity)
        if not identity:
            raise Unreachable(f"{resource.kind}: nothing to recognise it by")
        where = " AND ".join(f"{column} = {self.sql.mark}" for column in identity)
        found = self.sql.rows(
            f"SELECT * FROM {self.table(resource)} WHERE {where}",
            tuple(identity.values()),
        )
        return found[0] if found else None

    def find_many(self, resources: list[Resource]) -> list[Record | None]:
        """Every one of these, one question per table, answered in the order asked.

        One recognised by several columns is asked for on its own, which is what `find` already does.
        """
        answers: dict[int, Record | None] = {}
        grouped: dict[tuple[str, str], list[Resource]] = {}
        for one in resources:
            if len(one.identity) == 1:
                grouped.setdefault((self.table(one), next(iter(one.identity))), []).append(one)
            else:
                answers[id(one)] = self.find(one)

        for (table, column), mine in grouped.items():
            wanted = [one.identity[column] for one in mine]
            rows = self.sql.rows(
                f"SELECT * FROM {table} WHERE {column} IN ({self.sql.marks(len(wanted))})",
                tuple(wanted),
            )
            by_value = {str(row.get(column)): row for row in rows}
            for one in mine:
                answers[id(one)] = by_value.get(str(one.identity[column]))
        return [answers[id(one)] for one in resources]

    def create(self, resource: Resource) -> Record:
        columns = self._columns(resource)
        names = ", ".join(columns)
        self.sql.execute(
            f"INSERT INTO {self.table(resource)} ({names}) VALUES ({self.sql.marks(len(columns))})",
            tuple(columns.values()),
        )
        found = self.find(resource)
        if found is None:
            raise Unreachable(f"{self.table(resource)}: the row was written and cannot be read back")
        return found

    def update(self, resource: Resource, found: Record, changes: Record) -> Record:
        assignments = ", ".join(f"{column} = {self.sql.mark}" for column in changes)
        key = self._id_field(resource)
        self.sql.execute(
            f"UPDATE {self.table(resource)} SET {assignments} WHERE {key} = {self.sql.mark}",
            (*changes.values(), found[key]),
        )
        return {**found, **changes}

    def delete(self, resource: Resource, found: Record) -> None:
        key = self._id_field(resource)
        self.sql.execute(
            f"DELETE FROM {self.table(resource)} WHERE {key} = {self.sql.mark}",
            (found[key],),
        )

    # --- The optional ones ------------------------------------------------------------------------

    def browse(self, resource: Resource) -> list[Record]:
        """Every row of this kind."""
        return self.sql.rows(f"SELECT * FROM {self.table(resource)}")

