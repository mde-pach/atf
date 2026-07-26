from __future__ import annotations

from datetime import UTC, datetime

import pytest

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


def test_now_offsets():
    now = datetime(2026, 7, 25, 10, 30, tzinfo=UTC)
    assert resolve("${now+3d 09:00}", lookup({}), now=now) == "2026-07-28T09:00:00Z"
    assert resolve("${now-1d 23:59}", lookup({}), now=now) == "2026-07-24T23:59:00Z"
    assert resolve("${now+0d 00:00}", lookup({}), now=now) == "2026-07-25T00:00:00Z"


def test_references_finds_node_ids():
    value = {"a": "${accounts.primary.id}", "b": ["x-${projects.alpha.id}", "${now+1d 09:00}"]}
    assert references(value) == {"accounts.primary", "projects.alpha"}
