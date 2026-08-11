"""The little todo app this suite tests. Not part of ATF — it is the product under test.

It has a Python API and a command line over it, which is the ordinary shape of an application. The
suite's adapter goes through that API; the scenarios go through the command line.
"""

import sqlite3
import sys

SCHEMA = """
  CREATE TABLE IF NOT EXISTS owners (id INTEGER PRIMARY KEY, email TEXT UNIQUE);
  CREATE TABLE IF NOT EXISTS lists  (id INTEGER PRIMARY KEY, slug TEXT UNIQUE,
                                     owner_id INTEGER REFERENCES owners(id));
  CREATE TABLE IF NOT EXISTS tasks  (id INTEGER PRIMARY KEY, slug TEXT UNIQUE, done INTEGER,
                                     todo_list_id INTEGER REFERENCES lists(id));
  CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, slug TEXT UNIQUE, body TEXT);
  CREATE TABLE IF NOT EXISTS guests (id INTEGER PRIMARY KEY, nickname TEXT UNIQUE);
  CREATE TABLE IF NOT EXISTS plans  (id INTEGER PRIMARY KEY, code TEXT UNIQUE);
  CREATE TABLE IF NOT EXISTS tenants (id INTEGER PRIMARY KEY, region TEXT, code TEXT,
                                     UNIQUE (region, code));
"""
# The `plans` table is here and stays empty. `Plan` is declared `when_absent="require"`, so the row
# is somebody else's job — a migration, an ops runbook — and ATF says so rather than making one.


class Todo:
    """The application's own API. A service layer, an ORM or a client would sit here instead."""

    def __init__(self, path="todo.db"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # --- owners ---------------------------------------------------------------------------------

    def find_owner(self, email):
        row = self.db.execute("SELECT * FROM owners WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None

    def create_owner(self, email):
        self.db.execute("INSERT INTO owners (email) VALUES (?)", (email,))
        self.db.commit()
        return self.find_owner(email)

    def delete_owner(self, email):
        self.db.execute("DELETE FROM owners WHERE email = ?", (email,))
        self.db.commit()

    # --- lists ----------------------------------------------------------------------------------

    def find_list(self, slug):
        row = self.db.execute("SELECT * FROM lists WHERE slug = ?", (slug,)).fetchone()
        return dict(row) if row else None

    def create_list(self, owner_id, slug):
        self.db.execute("INSERT INTO lists (slug, owner_id) VALUES (?, ?)", (slug, owner_id))
        self.db.commit()
        return self.find_list(slug)

    def delete_list(self, slug):
        self.db.execute("DELETE FROM lists WHERE slug = ?", (slug,))
        self.db.commit()

    def every_list(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM lists")]

    def lists_of(self, email):
        rows = self.db.execute(
            """SELECT lists.slug FROM lists
               JOIN owners ON owners.id = lists.owner_id
               WHERE owners.email = ?""",
            (email,),
        ).fetchall()
        return [row["slug"] for row in rows]


# --- the command line -------------------------------------------------------------------------


def add(app, email, slug):
    owner = app.find_owner(email)
    if owner is None:
        sys.exit(f"no owner {email}")
    app.create_list(owner["id"], slug)


def show(app, email):
    print("\n".join(app.lists_of(email)) or "no lists")


if __name__ == "__main__":
    {"add": add, "show": show}[sys.argv[1]](Todo(), *sys.argv[2:])
