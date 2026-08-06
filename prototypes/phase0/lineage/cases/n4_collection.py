"""The shape the current design has no answer for.

A tournament needs sixteen players and some games to exist. None of them joins it, so there is no
foreign key and no single-valued field to type. `arrange.md#lineage` admits the near miss — "a
resource that needs another one only sometimes, or needs one of three types, has nowhere to say so"
— but this is a third thing again: a dependency of existence and of count.
"""

from ..declare import sqlite


@sqlite(table="players", unique_by="handle")
class Player:
    handle: str


@sqlite(table="games", unique_by="code")
class Game:
    code: str


@sqlite(table="tournaments", unique_by="slug")
class Tournament:
    slug: str
    players: list[Player]
    games: list[Game]
