"""The grammar a step pattern is written in: wording with `{captures}` in it."""

from __future__ import annotations

import re

# A `{capture}` in a step pattern, with the optional `:format` suffix a reader may write.
CAPTURE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::[^{}]*)?\}")


def fill(pattern: str, values: dict[str, str]) -> str:
    """A pattern with its `{captures}` replaced by the values chosen for them.

    A capture with no value keeps its placeholder.
    """
    return CAPTURE_RE.sub(lambda match: values.get(match.group(1)) or match.group(0), pattern)


def pattern_regex(pattern: str) -> str:
    """A pattern as a regular expression: literals escaped, every capture a wildcard."""
    pieces = CAPTURE_RE.split(pattern)
    out = [re.escape(pieces[0])]
    for index in range(1, len(pieces), 2):
        out.append("(.+?)")
        out.append(re.escape(pieces[index + 1]))
    return "".join(out)


def literal_length(pattern: str) -> int:
    """How much of a pattern is wording, as against a hole for a value.

    This is what decides between two sentences that both match: the reader meant the more particular
    of them, and wording is what makes one more particular than the other.
    """
    return len(CAPTURE_RE.sub("", pattern))
