"""What a test needs to exist before it runs.

`Owner` and `TodoList` belong to the API, so they are declared over it. `Task` is a row the API has
no endpoint for, so it is declared over the database. Both systems ship with ATF.
"""

from __future__ import annotations

from pathlib import Path

from models import open_database

from atf import needs
from atf.resources.process import Process
from atf.resources.rest import Record
from atf.resources.sql import Row

# The application owns its schema, and opening the database is what creates it. Done here so that
# `atf plan` can read what the tables hold unique before anything has been run.
open_database(str(Path(__file__).resolve().parents[1] / "todo.db"))


def an_email() -> str:
    """Whatever varies. ATF generates no values; this is the suite's own provider."""
    from itertools import count

    an_email.n = getattr(an_email, "n", count(1))
    return f"generated-{next(an_email.n)}@example.com"


class Api(Process, lives="the run"):
    """The API under test, started for the run and stopped when it ends.

    `port` is what makes it safe: the process does not count as made until the port answers, so
    nothing downstream races it.
    """

    command: Process.Key[str] = "python api.py"
    port: int = 8801


class Listed(Record):
    """What `Owner` and `TodoList` share: this API answers a listing as `{"items": [...]}`.

    Not a config option every other API would carry and never use — an override, written once,
    beside the two declarations it applies to. `find`'s own field-matching logic is untouched;
    only how the raw collection is fetched changes.
    """

    def _collection(self, params: dict | None = None) -> list[dict]:
        url = type(self)._path()
        response = self.http.client.get(url, params=dict(params or {}))
        return response.json().get("items", [])


class Owner(Listed, at="/owners"):
    api: Api = needs()
    email: Record.Key[str] = needs(an_email)


class TodoList(Listed, at="/lists"):
    owner: Owner = needs()
    slug: Record.Key[str]


class Task(Row, at="tasks"):
    todo_list: TodoList = needs()
    slug: Row.Key[str]
    done: bool = False


serving = Api()
primary = Owner(api=serving, email="primary@example.com")
groceries = TodoList(owner=primary, slug="groceries")
laundry = Task(todo_list=groceries, slug="laundry", done=False)
anyone = Owner(api=serving)
