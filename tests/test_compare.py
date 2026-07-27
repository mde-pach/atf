from __future__ import annotations

from datetime import UTC, datetime

import pytest

from atf.compare import describe, matches, same_instant, written_matches

# ---- matches: what an adapter's `find` uses --------------------------------


@pytest.mark.parametrize(
    "actual,expected",
    [
        ("a@b.test", "a@b.test"),
        (42, 42),
        (42, "42"),
        ("42", 42),
        (True, True),
        ("2026-07-25T09:00:00Z", "2026-07-25T09:00:00+00:00"),
        (datetime(2026, 7, 25, 9, 0, tzinfo=UTC), "2026-07-25T09:00:00Z"),
    ],
)
def test_matches_accepts_the_same_value_spelled_differently(actual, expected):
    assert matches(actual, expected)


@pytest.mark.parametrize("actual,expected", [("a", "b"), (1, 2), (None, "x"), (None, None)])
def test_matches_rejects_a_different_value(actual, expected):
    assert not matches(actual, expected)


def test_an_absent_value_never_matches_anything():
    """`find` asks whether the backend has this resource. No value at all means it does not."""
    assert not matches(None, "")
    assert not matches(None, 0)


def test_same_instant_needs_two_readable_moments():
    assert same_instant("2026-07-25T09:00:00Z", "2026-07-25T09:00:00+00:00")
    assert not same_instant("not a date", "2026-07-25T09:00:00Z")
    assert not same_instant(None, None)


# ---- written_matches: what a read-and-compare step uses --------------------


@pytest.mark.parametrize("written", ["false", "False", "FALSE", "no", "0"])
def test_a_boolean_reads_the_written_word(written):
    assert written_matches(False, written)
    assert not written_matches(True, written)


@pytest.mark.parametrize("written", ["true", "True", "yes", "1"])
def test_a_true_boolean_reads_the_written_word(written):
    assert written_matches(True, written)
    assert not written_matches(False, written)


def test_a_boolean_is_never_read_as_a_number():
    """`0 == False` in Python. A scenario writing "0" against a boolean means false, not zero."""
    assert not written_matches(0, "false")
    assert not written_matches(1, "true")


@pytest.mark.parametrize("actual,written", [(3, "3"), (3, "3.0"), (3.5, "3.5"), (3.0, "3")])
def test_a_number_is_compared_as_a_number(actual, written):
    assert written_matches(actual, written)


def test_a_number_against_words_does_not_match():
    assert not written_matches(3, "three")


@pytest.mark.parametrize("written", ["", "null", "none", "NULL", "  "])
def test_an_absent_value_is_written_as_empty(written):
    assert written_matches(None, written)


def test_an_absent_value_does_not_match_a_real_one():
    assert not written_matches(None, "standard")


def test_text_compares_as_text():
    assert written_matches("Buy milk", "Buy milk")
    assert not written_matches("Buy milk", "buy milk")


def test_a_timestamp_matches_across_formats():
    assert written_matches("2026-07-25T09:00:00Z", "2026-07-25T09:00:00+00:00")


def test_a_structured_value_is_compared_as_json():
    assert written_matches(["a", "b"], '["a", "b"]')
    assert written_matches({"a": 1}, '{"a": 1}')
    assert not written_matches(["a"], '["b"]')
    assert not written_matches(["a"], "a")


# ---- describe: how a failure names a value ---------------------------------


@pytest.mark.parametrize(
    "value,text",
    [
        (None, "nothing"),
        (False, "false (a true/false value)"),
        (True, "true (a true/false value)"),
        (3, "3 (a number)"),
        ("Buy milk", '"Buy milk"'),
        ([1, 2], "a list of 2 items"),
        ([1], "a list of 1 item"),
        ({"a": 1, "b": 2}, "a record with a, b"),
        ({}, "a record with no fields"),
    ],
)
def test_describe_names_the_kind_of_thing_as_well_as_the_value(value, text):
    assert describe(value) == text
