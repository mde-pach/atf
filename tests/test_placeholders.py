"""`${...}` resolved: a small language, and the rules it is read by.

That placeholders *work* is said everywhere in `tests/specs` — every chained resource in every suite
template hangs off `${owners.primary.id}`, and `specs/features/providers.feature` says what a
generated value does and what an unresolvable one says. This is the grammar underneath.

Four rules, each a decision over one string: a placeholder that is the whole value keeps its type
while one interpolated into a sentence becomes text; resolution reaches through nested mappings and
lists; a reference to something that was never provisioned raises rather than resolving to nothing;
and a form nobody registered says so instead of being left in the value to confuse a backend.

A pure function over text, kept as one — and paired with `test_compare.py`, which is the same shape
of thing at the other end of the same journey.
"""


from __future__ import annotations

from datetime import UTC, datetime

import pytest

from atf import providers
from atf.placeholders import Unresolved, references, resolve


def lookup(known: dict[str, object]):
    return lambda nid: known.get(nid)


def test_whole_string_placeholder_keeps_type():
    assert resolve("${accounts.primary.id}", lookup({"accounts.primary": 42})) == 42


def test_interpolated_placeholder_becomes_text():
    out = resolve("acct-${accounts.primary.id}-x", lookup({"accounts.primary": 42}))
    assert out == "acct-42-x"


def test_nested_structures():
    known = lookup({"accounts.primary": "A1", "projects.alpha": "P1"})
    value = {"a": ["${accounts.primary.id}", {"b": "${projects.alpha.id}"}], "c": 3, "d": None}
    assert resolve(value, known) == {"a": ["A1", {"b": "P1"}], "c": 3, "d": None}


def test_unresolved_dependency_raises():
    with pytest.raises(Unresolved) as err:
        resolve("${accounts.primary.id}", lookup({}))
    assert "accounts.primary" in str(err.value)


def test_unknown_placeholder_form_raises():
    with pytest.raises(Unresolved):
        resolve("${wat}", lookup({}))


@pytest.fixture
def fixed_clock():
    """`now` pinned, the same way a suite would pin it — through the registry."""
    at = datetime(2026, 7, 25, 10, 30, tzinfo=UTC)
    providers.register("now", lambda settings: providers.Now({"at": at}))
    yield at
    providers.register("now", providers.Now)


def test_now_offsets(fixed_clock):
    assert resolve("${now+3d 09:00}", lookup({})) == "2026-07-28T09:00:00Z"
    assert resolve("${now-1d 23:59}", lookup({})) == "2026-07-24T23:59:00Z"
    assert resolve("${now+0d 00:00}", lookup({})) == "2026-07-25T00:00:00Z"


def test_references_finds_node_ids():
    value = {"a": "${accounts.primary.id}", "b": ["x-${projects.alpha.id}", "${now+1d 09:00}"]}
    assert references(value) == {"accounts.primary", "projects.alpha"}
