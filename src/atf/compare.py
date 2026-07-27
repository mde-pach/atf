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
