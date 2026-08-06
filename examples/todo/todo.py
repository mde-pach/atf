"""The 25-line command line this suite tests. Not part of ATF — it is the product under test."""

import sqlite3
import sys

db = sqlite3.connect("todo.db")
db.executescript("""
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
""")
# The `plans` table is here and stays empty. `Plan` is declared `when_absent="require"`, so the row
# is somebody else's job — a migration, an ops runbook — and ATF says so rather than making one.


def add(email, slug):
    owner = db.execute("SELECT id FROM owners WHERE email = ?", (email,)).fetchone()
    if owner is None:
        sys.exit(f"no owner {email}")
    db.execute("INSERT INTO lists (slug, owner_id) VALUES (?, ?)", (slug, owner[0]))
    db.commit()


def show(email):
    rows = db.execute(
        """SELECT lists.slug FROM lists
           JOIN owners ON owners.id = lists.owner_id
           WHERE owners.email = ?""",
        (email,),
    ).fetchall()
    print("\n".join(row[0] for row in rows) or "no lists")


{"add": add, "show": show}[sys.argv[1]](*sys.argv[2:])
