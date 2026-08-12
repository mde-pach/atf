"""The worked example: a driver over the application's own API, and the adapters on top of it.

This is what a real suite writes. It never touches the database — it goes through `todo.Todo`, the
same API the product's own command line uses, so arranging a resource exercises the code that makes
one rather than a second implementation of it.
"""

from __future__ import annotations

from typing import Any, TypedDict

from todo import Todo

from atf import Resource, adapter, driver

Record = dict[str, Any]


@driver("todo")
class App:
    """The application, opened once per environment.

    `@driver("todo")` binds this class into this module under the name `todo`, which is what
    `resources.py` imports, and claims the `todo:` block of each environment.
    """

    class Settings(TypedDict):
        """What an environment configures."""

        path: str

    def __init__(self, settings: Settings) -> None:
        self.app = Todo(settings["path"])


@adapter("owner", driver="todo")
class Owners:
    """An owner of the application. Registered as `todo.owner`, said as `@todo.owner(...)`."""

    #: An owner is its email. There is no second way to recognise one, so no declaration says it.
    recognised_by = ("email",)

    def __init__(self, todo: App) -> None:
        self.app = todo.app

    def find(self, resource: Resource) -> Record | None:
        return self.app.find_owner(resource.identity["email"])

    def create(self, resource: Resource) -> Record:
        return self.app.create_owner(resource.values["email"])

    def delete(self, resource: Resource, found: Record) -> None:
        self.app.delete_owner(found["email"])


@adapter("list", driver="todo")
class Lists:
    """A todo list. It carries nothing but its identity, so there is no `update` to write."""

    recognised_by = ("slug",)

    def __init__(self, todo: App) -> None:
        self.app = todo.app

    def find(self, resource: Resource) -> Record | None:
        return self.app.find_list(resource.identity["slug"])

    def create(self, resource: Resource) -> Record:
        """The owner arrives already made, as the key it was made under.

        A scenario can drop it — `And "owner" is "null"` — so it is asked for, never assumed.
        """
        owner = resource.parents.get("owner")
        return self.app.create_list(owner.key if owner else None, resource.values["slug"])

    def delete(self, resource: Resource, found: Record) -> None:
        self.app.delete_list(found["slug"])

    def browse(self, resource: Resource) -> list[Record]:
        """Every list — what `the environment has 2 todo_list` counts."""
        return self.app.every_list()
