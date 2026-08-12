"""`atf run --accept`: the claims ATF drafts into a scenario that made none."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import literals
from .feature import Scenario

#: How much of a text field is worth proposing a claim about. Longer than this and the reader is
#: being asked to approve a paragraph, which is not approving.
LONGEST = 60


def promises_nothing(scenario: Scenario) -> bool:
    """Whether this scenario has no `Then` at all — the whole of the signal."""
    return not any(line.keyword == "then" for line in scenario.lines) and any(
        line.keyword == "when" for line in scenario.lines
    )


def draft(result: Any) -> list[str]:
    """The claims worth proposing about what an act produced, as sentences.

    More than you want: what comes back is a draft to cut down.
    """
    if isinstance(result, dict):
        return _about_record(result)
    if isinstance(result, list):
        return [f"Then there are {len(result)} of them"]
    if result is None:
        return []
    return [f"Then it mentions {_written(result)}"]


def _about_record(record: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for name, value in record.items():
        if name.startswith("_") or isinstance(value, dict | list):
            continue
        said = name.replace("_", " ")
        # A quoted value is literal, so one that spans lines cannot be written as an `is` at all.
        # It becomes a `mentions` of the few distinctive things in it, which is the useful draft.
        if isinstance(value, str) and (len(value) > LONGEST or "\n" in value):
            out += [f"Then it mentions {_written(word)}" for word in _worth_saying(value)]
            continue
        out.append(f"Then its {said} is {_written(value)}")
    return out


def _worth_saying(text: str) -> list[str]:
    """The few distinctive things in a long output. Three at most: a draft, not a transcript."""
    words = [one.strip(" .,:;\"'") for one in text.split()]  # split() breaks on newlines too
    interesting = [one for one in words if len(one) > 3 and not one.isdigit()]
    seen: list[str] = []
    for one in interesting:
        if one not in seen:
            seen.append(one)
    return seen[:3]


def _written(value: Any) -> str:
    """A value as a scenario would write it. Quoting carries the type, so this decides the quotes."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return literals.NOTHING
    if isinstance(value, int | float):
        return str(value)
    return f'"{value}"'


def write_into(path: Path, scenario: Scenario, claims: list[str]) -> int:
    """Put the drafted claims into the file, under the scenario's last sentence.

    Written as sentences, in the file, for you to read and cut down — never applied silently and
    never held anywhere but where you would look for them.
    """
    if not claims:
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    last = max((line.number for line in scenario.lines), default=scenario.number)
    indent = _indent(lines[last - 1]) if last <= len(lines) else "    "
    drafted = [f"{indent}{one}" if index == 0 else f"{indent}And {one[5:]}" for index, one in enumerate(claims)]
    lines[last:last] = drafted
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(drafted)


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def summary(written: dict[str, int]) -> list[str]:
    """What was drafted, and the one instruction: delete what you do not care about."""
    if not written:
        return []
    total = sum(written.values())
    out = [f"drafted {total} claims into {len(written)} scenarios — read them and cut them down"]
    out += [f"  {name}: {count}" for name, count in sorted(written.items())]
    return out
