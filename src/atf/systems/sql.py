"""`Row` — a row in a table, recognised by whatever `Row.Key` names."""

from __future__ import annotations

import importlib
from typing import Any, ClassVar, TypedDict
from urllib.parse import urlparse

from typing_extensions import override

from ..declare import (
    Driver,
    DriverProperty,
    Resource,
    Unreachable,
    declaration_of,
    instance_of,
    is_resource,
    register_system,
)
from ..spi import Payload

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
    """One table, as `_held` reads it back to know which columns a write may use."""
    return {
        "table": name,
        "columns": [{"name": one, "type": kind} for one, kind in columns],
        "key": keys[0] if len(keys) == 1 else "",
        "uniques": sorted(unique, key=len),
        "unique_by": unique[0][0] if unique and len(unique[0]) == 1 else "",
        "parents": parents,
    }


class Sql(Driver):
    """One connection, over any DB-API module named by the environment's URL.

    A step asks for this by the name `sql`; `Row` works through it as `self.sql`.
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
        """What this driver is pointed at, for a message about not reaching it."""
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

    def rows(self, statement: str, values: tuple[Any, ...] = ()) -> list[Payload]:
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
        """Every table this database holds: its name, its columns, and what it points at.

        Read once, held for the driver's life — `Row._held` asks this per write, and the answer
        does not change mid-run.
        """
        if self.module_name == "sqlite3":
            return [self._describe_sqlite(name) for name in self._sqlite_tables()]
        return [self._describe_standard(name) for name in self._standard_tables()]

    def schema(self) -> list[dict[str, Any]]:
        """The same, read once and held."""
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


class Row(Resource):
    """One row in a table, recognised by whatever field its declaration marks `Row.Key`."""

    #: The table this kind maps to, as `at=` wrote it. Sql's own setting, not ATF's — read from
    #: the class alone, since building a query needs it before any instance exists.
    at: ClassVar[str] = ""
    sql = DriverProperty[Sql]("sql")
    #: What this schema calls the primary key — the column `update`/`delete` write through.
    id_field: ClassVar[str] = "id"
    #: What a column holding a parent is called: `owner` becomes `owner_id`.
    parent_suffix: ClassVar[str] = "_id"

    def __init_subclass__(cls, *, at: str = "", **rest: Any) -> None:
        if at:
            cls.at = at
        super().__init_subclass__(**rest)

    @classmethod
    def _table(cls) -> str:
        return cls.at or cls.__name__.lower()

    def _identity(self) -> Payload:
        return {name: getattr(self, name) for name in declaration_of(self).key}

    def _held(self) -> set[str]:
        """Every column this table has, as the schema says."""
        table = type(self)._table()
        for one in self.sql.schema():
            if one["table"] == table:
                return {str(column["name"]) for column in one["columns"]}
        return set()

    def _columns(self) -> Payload:
        """The declared fields, and each parent as the key of the row it was made as.

        A parent the table has no column for is left out. Something can have to exist first and
        leave no trace in the row, and whether it does is a fact the schema holds.
        """
        held = self._held()
        columns: Payload = {}
        for field, value in instance_of(self).values.items():
            if not is_resource(value):
                columns[field] = value
                continue
            key = f"{field}{type(self).parent_suffix}"
            if held and key not in held:
                continue
            identity = instance_of(value).identity
            if identity is None:
                raise Unreachable(f"{field}: the parent it points at has not been made")
            columns[key] = identity
        return columns

    def _found_or_none(self) -> Payload | None:
        return self.find()

    # --- The four ---------------------------------------------------------------------------------

    @override
    def find(self) -> Payload | None:
        identity = self._identity()
        if not identity:
            raise Unreachable(f"{type(self).__name__}: nothing to recognise it by")
        where = " AND ".join(f"{column} = {self.sql.mark}" for column in identity)
        found = self.sql.rows(
            f"SELECT * FROM {type(self)._table()} WHERE {where}",
            tuple(identity.values()),
        )
        return found[0] if found else None

    @classmethod
    def find_many(cls, resources: list[Row]) -> list[Payload | None]:
        """Every one of these, one question per table, answered in the order asked.

        One recognised by several columns is asked for on its own, which is what `find` already does.
        """
        answers: dict[int, Payload | None] = {}
        grouped: dict[tuple[str, str], list[Row]] = {}
        for one in resources:
            keys = declaration_of(one).key
            if len(keys) == 1:
                grouped.setdefault((type(one)._table(), keys[0]), []).append(one)
            else:
                answers[id(one)] = one.find()

        for (table, column), mine in grouped.items():
            sql = mine[0].sql
            wanted = [getattr(one, column) for one in mine]
            rows = sql.rows(
                f"SELECT * FROM {table} WHERE {column} IN ({sql.marks(len(wanted))})",
                tuple(wanted),
            )
            by_value = {str(row.get(column)): row for row in rows}
            for one in mine:
                answers[id(one)] = by_value.get(str(getattr(one, column)))
        return [answers[id(one)] for one in resources]

    @override
    def create(self) -> Payload:
        columns = self._columns()
        names = ", ".join(columns)
        self.sql.execute(
            f"INSERT INTO {type(self)._table()} ({names}) VALUES ({self.sql.marks(len(columns))})",
            tuple(columns.values()),
        )
        found = self.find()
        if found is None:
            raise Unreachable(f"{type(self)._table()}: the row was written and cannot be read back")
        return found

    @override
    def update(self, changes: Payload) -> Payload:
        found = self._found_or_none()
        if found is None:
            raise Unreachable(f"{type(self)._table()}: updating a row that is not there")
        key = type(self).id_field
        assignments = ", ".join(f"{column} = {self.sql.mark}" for column in changes)
        self.sql.execute(
            f"UPDATE {type(self)._table()} SET {assignments} WHERE {key} = {self.sql.mark}",
            (*changes.values(), found[key]),
        )
        return {**found, **changes}

    @override
    def delete(self) -> None:
        found = self._found_or_none()
        if found is None:
            return
        key = type(self).id_field
        self.sql.execute(
            f"DELETE FROM {type(self)._table()} WHERE {key} = {self.sql.mark}",
            (found[key],),
        )

    # --- The optional ones ------------------------------------------------------------------------

    def browse(self) -> list[Payload]:
        """Every row of this kind."""
        return self.sql.rows(f"SELECT * FROM {type(self)._table()}")


register_system(Row, Sql, "row")
