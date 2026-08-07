"""Turning what a system already holds into the declarations that describe it."""

from __future__ import annotations

import keyword
import re
from typing import Any

from .environment import Ground
from .spi import offers

#: SQL type to the annotation a declaration writes. Anything unrecognised is read as text.
TYPES: tuple[tuple[str, str], ...] = (
    ("bool", "bool"),
    ("int", "int"),
    ("serial", "int"),
    ("bigint", "int"),
    ("smallint", "int"),
    ("numeric", "float"),
    ("decimal", "float"),
    ("real", "float"),
    ("double", "float"),
    ("float", "float"),
)


class AdoptError(Exception):
    """Raised when nothing in this environment can say what it holds."""


def annotation(sql_type: str) -> str:
    """The Python type a column's declared type reads as."""
    lowered = sql_type.lower()
    for fragment, written in TYPES:
        if fragment in lowered:
            return written
    return "str"


def singular(word: str) -> str:
    """`owners` -> `owner`. Blunt, and a name is the one thing a reader will correct anyway."""
    if word.endswith("ies") and len(word) > 3:
        return f"{word[:-3]}y"
    if word.endswith(("sses", "shes", "ches", "xes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def class_name(table: str) -> str:
    """`todo_lists` -> `TodoList`."""
    parts = [one for one in re.split(r"[^0-9A-Za-z]+", singular(table)) if one]
    name = "".join(part[:1].upper() + part[1:] for part in parts)
    return name or "Thing"


def field_name(column: str, suffix: str = "_id") -> str:
    """What a column holding a parent is called once the parent is the value: `owner_id` -> `owner`."""
    bare = column[: -len(suffix)] if column.endswith(suffix) and len(column) > len(suffix) else column
    return f"{bare}_" if keyword.iskeyword(bare) else bare


def ordered(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tables with the ones they point at first, so a class is written after what it names."""
    by_name = {one["table"]: one for one in tables}
    out: list[dict[str, Any]] = []
    placed: set[str] = set()

    def place(name: str, trail: tuple[str, ...]) -> None:
        if name in placed or name in trail or name not in by_name:
            return
        for parent in dict.fromkeys(by_name[name]["parents"].values()):
            place(parent, (*trail, name))
        placed.add(name)
        out.append(by_name[name])

    for one in tables:
        place(one["table"], ())
    return out


def declaration(table: dict[str, Any], system: str) -> str:
    """One table as the class that declares it, with what could not be worked out said in a comment."""
    name = class_name(table["table"])
    parents = dict(table["parents"])
    recognised = table["unique_by"]

    options = [f'table="{table["table"]}"']
    options.append(f'unique_by="{recognised}"' if recognised else 'unique_by=""')
    if table["key"] and table["key"] != "id":
        options.append(f'id_field="{table["key"]}"')
    if parents:
        kinds = dict.fromkeys(class_name(one) for one in parents.values())
        options.append(f"depends_on=[{', '.join(kinds)}]")

    lines = [f"@{system}({', '.join(options)})", f"class {name}:"]
    if not recognised:
        lines += [
            f'    """{table["table"]} has no single unique column.',
            "",
            "    Name the field that recognises one row and put it in `unique_by`.",
            '    """',
            "",
        ]

    body: list[str] = []
    for column in table["columns"]:
        one = column["name"]
        if one == table["key"]:
            continue
        if one in parents:
            body.append(f"    {field_name(one)}: {class_name(parents[one])}")
        else:
            body.append(f"    {field_name(one)}: {annotation(column['type'])}")
    lines += body or ["    pass"]
    return "\n".join(lines)


def source(tables: list[dict[str, Any]], system: str) -> str:
    """A whole `resources.py`, from what the environment said it holds."""
    if not tables:
        return (
            '"""What this suite needs to exist."""\n\n'
            f"from atf import {system}  # noqa: F401\n\n"
            "# This environment holds no tables to declare.\n"
        )
    head = [
        '"""What this suite needs to exist.',
        "",
        "Written by `atf adopt` from what the environment already holds. Every line here is a",
        "declaration you own: delete what you do not test, and name the particular ones you do.",
        '"""',
        "",
        f"from atf import {system}",
        "",
    ]
    bodies = [declaration(one, system) for one in ordered(tables)]
    tail = [
        "",
        "# Name the particular resources your tests ask for, one variable each:",
        "#",
        f"#     primary = {class_name(ordered(tables)[0]['table'])}(...)",
    ]
    return "\n".join(head) + "\n\n" + "\n\n\n".join(bodies) + "\n" + "\n".join(tail) + "\n"


def from_ground(ground: Ground) -> tuple[str, list[dict[str, Any]]]:
    """Ask every system in this environment what it holds, and write the declarations for it."""
    speaking = [
        (name, adapter)
        for name, adapter in sorted(ground.adapters.items())
        if offers(type(adapter), "describe")
    ]
    if not speaking:
        known = ", ".join(sorted(ground.adapters)) or "none"
        raise AdoptError(
            f"no system in {ground.config.name} can say what it holds "
            f"(its systems are: {known}; `describe` is the optional method this reads)"
        )
    system, adapter = speaking[0]
    tables = list(adapter.describe())
    return source(tables, system), tables
