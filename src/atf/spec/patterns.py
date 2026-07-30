"""The steps ATF defines, and the grammar a step pattern is written in. Dependency-free."""

from __future__ import annotations

import re

GIVEN, WHEN, THEN = "given", "when", "then"
ANY_KEYWORD = "*"
KEYWORDS = frozenset({GIVEN, WHEN, THEN, ANY_KEYWORD})

# ATF's own provisioning step. The only step definition the framework itself contributes, and the
# composer offers it as a resource picker and not as a line of wording, so it has to be recognisable
# by pattern wherever a step is read.
PROVISION = 'the {resource_type} "{name}"'
PROVISION_VARIED = 'the {resource_type} "{name}" but:'

# The same resource, isolated. `the todo_list "groceries"` is the shared one — found once, left in
# place, the same list for every scenario that names it. `a fresh todo_list "groceries"` is an
# instance of that node this scenario alone holds, torn down with it, and the catalog says nothing
# about it: isolation is a thing a *scenario* needs, and the type it needs one of is often the same
# type another scenario is happy to share.
#
# English, not a lifecycle keyword: "a fresh one" is what a person says about a glass, and the
# article carries the difference from "the" — the one everybody uses.
PROVISION_FRESH = 'a fresh {resource_type} "{name}"'
PROVISION_FRESH_VARIED = 'a fresh {resource_type} "{name}" but:'

# A `{capture}` in a step pattern, with the optional `:format` pytest-bdd's parse parser allows.
CAPTURE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::[^{}]*)?\}")

# A resource named in a step, whichever article names it: `the todo_list "groceries"` is the shared
# one and `a fresh todo_list "groceries"` is an instance of it — and a scenario that builds its own
# copy is still a scenario about that node, which is what the cockpit has to be able to say. The
# articles come from the patterns above, so a spelling cannot be added to one and not the other.
_ARTICLES = "|".join(
    re.escape(pattern.split("{", 1)[0].strip()) for pattern in (PROVISION, PROVISION_FRESH)
)
PROVISION_RE = re.compile(rf'\b(?:{_ARTICLES}) ([A-Za-z_][A-Za-z0-9_]*) "([^"]+)"')


def fill(pattern: str, values: dict[str, str]) -> str:
    """A step pattern with its `{captures}` replaced by the values chosen for them.

    A capture with no value keeps its placeholder, so a half-built step reads as a half-built step
    and not as a sentence with a hole silently closed up.
    """
    return CAPTURE_RE.sub(lambda match: values.get(match.group(1)) or match.group(0), pattern)


def pattern_regex(pattern: str) -> str:
    """A step pattern as a regular expression: literals escaped, every capture a wildcard."""
    pieces = CAPTURE_RE.split(pattern)
    out = [re.escape(pieces[0])]
    for index in range(1, len(pieces), 2):
        out.append("(.+?)")
        out.append(re.escape(pieces[index + 1]))
    return "".join(out)


def literal_length(pattern: str) -> int:
    """How much of a pattern is wording, as against a hole for a value."""
    return len(CAPTURE_RE.sub("", pattern))
