"""Comparing a value someone wrote against a value a backend returned.

Two callers, one problem. An adapter's `find` matches a catalog body against a record: both sides
are already typed, because YAML gave them their types. A read-and-compare step matches a record
against a value quoted in Gherkin: that side is *always* a string, because Gherkin has no other
kind. `written_matches` is the second case layered on the first, so the rule that decides whether
`find` recognised a resource is the same rule that decides whether an assertion passed.

Pure functions; no I/O, no knowledge of any particular backend.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

# What a person writes in Gherkin for a value that is not there. `""` is the common one; the other
# two are what someone types when the empty string looks like a mistake.
BLANK = frozenset({"", "null", "none"})

TRUE = frozenset({"true", "yes", "1"})
FALSE = frozenset({"false", "no", "0"})


def matches(actual: Any, expected: Any) -> bool:
    """Whether a record's value is the one a catalog body asked for.

    Deliberately loose about spelling and strict about presence: a backend that returns an id as a
    string when the body wrote a number has still returned the right record, but a backend with no
    value at all has not.
    """
    if actual is None:
        return False
    if actual == expected:
        return True
    if str(actual) == str(expected):
        return True
    return same_instant(actual, expected)


def written_matches(actual: Any, written: str) -> bool:
    """Whether a record's value is the one a scenario wrote between quotes.

    Gherkin only has strings, so every comparison here is against text: `"false"` has to reach a
    boolean, `"3"` an integer, `""` an absent value. The type of the record's value decides how its
    text is read — never the other way round, because guessing a type from the written side is how
    `"0"` starts matching `false`.
    """
    text = written.strip()

    if isinstance(actual, bool):
        # Before the number branch: in Python a bool *is* an int, and `0 == False`.
        lowered = text.lower()
        return lowered in (TRUE if actual else FALSE)

    if actual is None:
        return text.lower() in BLANK

    if isinstance(actual, int | float):
        try:
            return float(actual) == float(text)
        except ValueError:
            return False

    if isinstance(actual, dict | list):
        try:
            return actual == json.loads(text)
        except ValueError:
            return False

    return matches(actual, text)


def written_contains(actual: Any, written: str) -> bool:
    """Whether a record's value holds the text a scenario wrote between quotes.

    Containment means one thing per kind of value, and only the kinds where it means something
    decidable are answered. Text holds a substring. A list holds an item, matched the same way a
    field is — so `contains "3"` finds the number 3. A record holds neither: `contains` over a
    record would have to guess between a key and a value, so it is refused and the reader is told
    to name the field inside it instead.
    """
    if actual is None:
        return False
    if isinstance(actual, str):
        return written in actual
    if isinstance(actual, list | tuple):
        return any(written_matches(item, written) for item in actual)
    if isinstance(actual, dict):
        raise Uncontainable(actual)
    return written in str(actual)


def is_empty(actual: Any) -> bool:
    """Whether a record's value is nothing, or a text, list or record with nothing in it.

    A number is not empty and neither is `false`: `0` and `false` are values a backend returned,
    and reading them as absence is the mistake `written_matches` orders its branches to avoid.
    """
    if actual is None:
        return True
    if isinstance(actual, str | list | tuple | dict):
        return len(actual) == 0
    return False


class Uncontainable(Exception):
    """`contains` was asked of a value where containment has no one meaning."""

    def __init__(self, actual: Any) -> None:
        self.actual = actual
        super().__init__(
            f"{describe(actual)} — a record holds keys and values both, so `contains` cannot say "
            "which was meant. Name the field inside it instead."
        )


# ---- markers ---------------------------------------------------------------
#
# A table row compares one field with one written value, and sometimes the value is not the point:
# an id is whatever the backend assigned, a timestamp is whatever `now` was. A marker says what
# *kind* of thing must be there instead of what it must equal.
#
# **The names follow Pact's matchers**, because this is not a new idea and a project that already
# publishes contracts should not have to learn a second vocabulary for the same act. `match.int(…)`,
# `match.str(…)`, `match.uuid(…)`, `match.datetime(…)`, `match.regex(…, regex=…)` are theirs;
# `#int`, `#str`, `#uuid`, `#datetime`, `#regex` are these. Where the two differ they differ for a
# reason worth knowing:
#
# - **A Pact matcher wraps an example value; a marker replaces it.** `match.int(12345)` keeps the
#   12345, because a pact file is a contract published to the provider team and needs concrete data
#   in it. A marker is an assertion — nobody downstream reads it — so there is nothing to keep.
# - **Presence has no Pact equivalent.** `#present`, `#absent`, `#notnull` and `#null` are about
#   whether a field is *there*, which Pact expresses structurally by the body's shape. A claim has
#   no body to shape, so it says it.
#
# Otherwise a closed list of things ATF can decide, so that every one of them can be offered in a
# dropdown — with `#regex` the single exception, because a pattern is the one kind of expectation
# that cannot be enumerated and Pact treats it as core.

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# The marker that takes an argument: `#regex ^AC-[0-9]+$`. Written with a space rather than
# brackets, because a table cell is already delimited and `#regex(^\|)` would need escaping a pipe
# inside brackets inside a cell.
REGEX_MARKER = "#regex"

MARKERS: dict[str, str] = {
    "#present": "the field is there, whatever it holds",
    "#absent": "the field is not there at all",
    "#notnull": "the field is there and holds something",
    "#null": "the field holds nothing",
    "#str": "text",
    "#int": "a whole number",
    "#decimal": "a number with a fractional part",
    "#number": "a number of either kind",
    "#bool": "a true/false value",
    "#uuid": "a UUID",
    "#date": "a date",
    "#datetime": "a date and a time",
    "#time": "a time of day",
    f"{REGEX_MARKER} <pattern>": "text matching the pattern written after it",
}

MISSING = object()
"""What `field_matches` is handed for a field the record does not carry at all."""


def is_marker(written: str) -> bool:
    text = written.strip()
    return text in MARKERS or text.split(" ", 1)[0] == REGEX_MARKER


def marker_matches(actual: Any, written: str) -> bool:
    """Whether a value is the *kind* of thing a marker asks for. `actual is MISSING` when absent."""
    marker = written.strip()
    there = actual is not MISSING
    if marker == "#present":
        return there
    if marker == "#absent":
        return not there
    if not there:
        return False
    if marker == "#notnull":
        return actual is not None
    if marker == "#null":
        return actual is None
    if marker == "#str":
        return isinstance(actual, str)
    if marker == "#bool":
        return isinstance(actual, bool)
    # Before the bool check would matter, every time: in Python a bool *is* an int, and a field
    # holding `true` is not a field holding 1.
    if marker == "#int":
        return isinstance(actual, int) and not isinstance(actual, bool)
    if marker == "#decimal":
        return isinstance(actual, float)
    if marker == "#number":
        return isinstance(actual, int | float) and not isinstance(actual, bool)
    if marker == "#uuid":
        return isinstance(actual, str) and bool(_UUID_RE.match(actual))
    if marker in ("#date", "#datetime", "#time"):
        return _is_moment(actual, marker)
    if marker.split(" ", 1)[0] == REGEX_MARKER:
        return _matches_pattern(actual, marker)
    return False


def _is_moment(actual: Any, marker: str) -> bool:
    """A date, a time, or both. Read with the same parser a datetime natural key is read with.

    A time on its own is not a `datetime`, so it is tried as one by borrowing a date nobody sees —
    which is what `fromisoformat` would want and is cheaper than a second parser.
    """
    if marker == "#time":
        return parse_datetime(f"1970-01-01T{str(actual).strip()}") is not None
    moment = parse_datetime(actual)
    if moment is None:
        return False
    # A date is a moment somebody wrote without a time on it, and that is a fact about the text.
    written_as_date = isinstance(actual, str) and "t" not in actual.strip().lower()
    return written_as_date if marker == "#date" else not written_as_date


def _matches_pattern(actual: Any, marker: str) -> bool:
    """`#regex <pattern>` — the one marker that takes an argument, and the one Pact calls core.

    A pattern that will not compile is not a match rather than a crash: the scenario is what is
    wrong, and it says so through the ordinary "did not hold" message with the pattern in it.
    """
    _, _, pattern = marker.partition(" ")
    if not pattern.strip() or not isinstance(actual, str):
        return False
    try:
        return re.search(pattern.strip(), actual) is not None
    except re.error:
        return False


def field_matches(actual: Any, written: str) -> bool:
    """One field against one written cell, marker or value. `actual is MISSING` when absent."""
    if is_marker(written):
        return marker_matches(actual, written)
    if actual is MISSING:
        return False
    return written_matches(actual, written)


def same_instant(actual: Any, expected: Any) -> bool:
    """Whether two values are the same moment written differently — `Z` against `+00:00`."""
    left, right = parse_datetime(actual), parse_datetime(expected)
    return left is not None and right is not None and left == right


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def describe(value: Any) -> str:
    """A value as a failure message should name it: what it was, and what kind of thing that is.

    An assertion that only reports `False != 'false'` sends the reader to the adapter to find out
    which side is which. Saying `false (a true/false value)` ends the question.
    """
    if value is None:
        return "nothing"
    if isinstance(value, bool):
        return f"{str(value).lower()} (a true/false value)"
    if isinstance(value, int | float):
        return f"{value} (a number)"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, list):
        return f"a list of {len(value)} item" + ("" if len(value) == 1 else "s")
    if isinstance(value, dict):
        return "a record with " + (", ".join(sorted(map(str, value))) or "no fields")
    return f"{value!r}"
