"""Guessing a natural key: a decision procedure over data, kept as one.

That `atf import openapi` writes resource types is a scenario — `specs/features/importing.feature`
runs the real command against a real suite, reads the file back, and checks the guess is written
with the reason that produced it. What is here is the arithmetic underneath that: which of six
signals fire for a given field, what they are worth relative to each other, and where the margin
between the leader and the runner-up stops being a decision.

A feature file is the wrong place for it, for the same reason `test_compare.py` is not one. Every
row below is one schema fragment differing from the last in one property — a `format`, a query
parameter, a `readOnly` flag, an existing key elsewhere in the catalog — and arranging each as a
suite on disk would mean thirty workspaces that differ by three characters. The scenario would be
longer than the table and would say less.

What the scenarios must own, and do, is the *behaviour*: a guess carries its reason, an ambiguous
one is refused rather than picked, and a catalog somebody has edited is never rewritten. What this
owns is only whether the sums come out the same way twice.
"""

from __future__ import annotations

import pytest

from atf.openapi import (
    Collection,
    Guess,
    collections,
    convention_of,
    guess_key,
    render,
    type_name,
)

TEXT = {"type": "string"}


def key(
    properties,
    required=(),
    filters=(),
    scope=(),
    id_field="id",
    convention=None,
    collection="/things",
):
    return guess_key(
        properties=properties,
        required=frozenset(required),
        filters=frozenset(filters),
        scope=tuple(scope),
        id_field=id_field,
        convention=convention or {},
        collection=collection,
    )


# ---- what the collection endpoint filters by beats everything else ----------


def test_a_field_the_collection_filters_by_wins():
    guess = key({"email": TEXT, "name": TEXT}, required=["name"], filters=["email"])
    assert guess.key == ("email",)
    assert "filters by it" in guess.because


def test_a_filter_that_is_not_a_settable_field_is_not_a_candidate():
    """`GET /things?since=` filters, and `since` is still not how a record is identified."""
    guess = key({"slug": TEXT}, required=["slug"], filters=["since"])
    assert guess.key == ("slug",)


# ---- the project's own convention, learned from its catalog ------------------


def test_a_field_this_catalog_already_keys_on_wins_a_close_call():
    guess = key({"name": TEXT, "slug": TEXT}, required=["name", "slug"], convention={"slug": ["owner"]})
    assert guess.key == ("slug",)
    assert "`owner` already uses it as its key" in guess.because


def test_the_convention_is_read_off_the_catalog_including_composite_keys():
    types = {
        "owner": {"natural_key": "slug"},
        "task": {"natural_key": ["owner_id", "slug"]},
        "note": {"natural_key": "reference"},
    }
    assert convention_of(types) == {"slug": ["owner", "task"], "owner_id": ["task"], "reference": ["note"]}


def test_a_convention_is_beaten_by_the_endpoint_actually_filtering():
    guess = key({"name": TEXT, "slug": TEXT}, filters=["name"], convention={"slug": ["owner"]})
    assert guess.key == ("name",)


# ---- shape: a field somebody bothered to constrain ---------------------------


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "string", "format": "email"},
        {"type": "string", "format": "uuid"},
        {"type": "string", "format": "hostname"},
        {"type": "string", "pattern": "^[A-Z]{3}-[0-9]+$"},
    ],
)
def test_a_constrained_string_beats_an_unconstrained_one(schema):
    guess = key({"marker": schema, "title": TEXT}, required=["marker", "title"])
    assert guess.key == ("marker",)


def test_a_format_nobody_identifies_records_by_is_no_help():
    guess = key({"colour": {"type": "string", "format": "color"}, "title": TEXT}, required=["colour", "title"])
    assert not guess


# ---- name resemblance: last, and only where nothing has been learned ---------


def test_a_key_shaped_name_decides_when_the_catalog_is_empty():
    guess = key({"slug": TEXT, "blurb": TEXT}, required=["slug", "blurb"])
    assert guess.key == ("slug",)
    assert "reads like a key" in guess.because


def test_a_key_shaped_name_is_silent_once_the_catalog_has_a_convention():
    """The whole point of the ranking: a project that has decided is not overruled by English."""
    guess = key({"slug": TEXT, "blurb": TEXT}, required=["slug", "blurb"], convention={"nothing_here": ["owner"]})
    assert not guess


# ---- what can never be a key -------------------------------------------------


@pytest.mark.parametrize(
    "field,schema",
    [
        ("id", TEXT),
        ("uuid", TEXT),
        ("created_at", {"type": "string", "format": "date-time"}),
        ("renewed_on", TEXT),
        ("updated", TEXT),
        ("active", {"type": "boolean"}),
        ("seats", {"type": "integer"}),
        ("settings", {"type": "object"}),
        ("labels", {"type": "array"}),
        ("description", TEXT),
        ("notes", TEXT),
        ("secret", {"type": "string", "readOnly": True}),
    ],
)
def test_a_field_that_cannot_identify_a_record_is_never_considered(field, schema):
    guess = key({field: schema}, required=[field], filters=[field])
    assert not guess
    assert guess.considered == ()


def test_the_declared_id_field_is_excluded_whatever_it_is_called():
    guess = key({"reference": TEXT, "handle": TEXT}, required=["reference", "handle"], id_field="reference")
    assert guess.key == ("handle",)


# ---- ambiguity is not resolved -----------------------------------------------


def test_two_equally_likely_fields_leave_no_key_and_say_what_was_considered():
    guess = key({"name": TEXT, "slug": TEXT}, required=["name", "slug"])
    assert guess.key == ()
    assert [one.field for one in guess.considered] == ["name", "slug"]
    assert "nothing was clearly ahead" in guess.because
    assert "`name`" in guess.because and "`slug`" in guess.because


def test_candidates_with_the_same_reasons_are_a_tie_whatever_they_are_called():
    """Nothing separates them, so there is nothing to prefer one by — and a preference is invented."""
    guess = key({"title": TEXT, "blurb": TEXT}, required=["title", "blurb"])
    assert guess.key == ()


def test_one_reason_the_runner_up_does_not_have_is_enough_to_decide():
    guess = key({"slug": TEXT, "title": TEXT}, required=["slug", "title"])
    assert guess.key == ("slug",)


def test_a_field_with_no_signal_at_all_never_makes_the_leader_look_ambiguous():
    guess = key({"email": {"type": "string", "format": "email"}, "title": TEXT}, required=["email"])
    assert guess.key == ("email",)


def test_a_schema_that_says_nothing_produces_no_key_and_says_so():
    guess = key({})
    assert not guess
    assert "nothing in the schema" in guess.because


# ---- path scoping is not a guess ---------------------------------------------


def test_a_scoping_field_leads_the_composite_key():
    guess = key({"slug": TEXT}, required=["slug"], filters=["slug"], scope=["account_id"])
    assert guess.key == ("account_id", "slug")


def test_a_scoping_field_is_not_itself_a_candidate():
    guess = key({"account_id": TEXT, "slug": TEXT}, required=["account_id", "slug"], scope=["account_id"])
    assert guess.key == ("account_id", "slug")


def test_a_scope_with_nothing_to_pair_it_with_is_still_no_key():
    """A key of nothing but the parent's identity matches every child that parent has."""
    guess = key({"count": {"type": "integer"}}, scope=["account_id"])
    assert not guess


# ---- the same answer twice ---------------------------------------------------


def test_the_guess_does_not_depend_on_the_order_the_properties_arrive_in():
    forwards = key({"email": {"type": "string", "format": "email"}, "name": TEXT}, required=["email", "name"])
    backwards = key({"name": TEXT, "email": {"type": "string", "format": "email"}}, required=["name", "email"])
    assert forwards == backwards


# ---- reading a path ----------------------------------------------------------


@pytest.mark.parametrize(
    "segment,expected",
    [
        ("accounts", "account"),
        ("companies", "company"),
        ("addresses", "address"),
        ("boxes", "box"),
        ("status", "statu"),  # the four rules everybody knows, and nothing else — renamed once
        ("access", "access"),
        ("todo-lists", "todo_list"),
        ("Accounts", "account"),
        ("2fa", ""),
        ("", ""),
    ],
)
def test_a_path_segment_becomes_a_type_name(segment, expected):
    assert type_name(segment) == expected


def test_an_item_path_declares_no_type_of_its_own():
    document = {"paths": {"/accounts": {"post": {}}, "/accounts/{account_id}": {"get": {}}}}
    assert [one.name for one in collections(document, {})] == ["account"]


def test_a_nested_collection_names_the_type_it_hangs_off():
    document = {"paths": {"/accounts/{account_id}/projects": {"get": {}}}}
    found = collections(document, {})[0]
    assert (found.name, found.scope, found.parent) == ("project", ("account_id",), "account")


# ---- what gets written -------------------------------------------------------


def test_a_guess_is_written_with_the_reason_beside_it():
    written = render(Collection(name="account", path="/accounts", id_field="id", guess=Guess(("email",), "reasons")))
    assert "  # guessed: reasons\n  natural_key: email\n" in written


def test_no_guess_is_written_as_no_key_and_what_was_considered():
    written = render(Collection(name="label", path="/labels", id_field="id", guess=Guess((), "it was a tie")))
    assert "natural_key" not in written.replace("no natural_key", "")
    assert "# no natural_key: it was a tie" in written


def test_a_scoped_type_is_written_with_a_listing_path_it_can_fill_in():
    written = render(
        Collection(
            name="project",
            path="/accounts/{account_id}/projects",
            id_field="id",
            guess=Guess(("account_id", "slug"), "reasons"),
            scope=("account_id",),
            parent="account",
        )
    )
    assert "  list_path: /accounts/{account_id}/projects\n" in written
    assert "natural_key: [account_id, slug]" in written
    assert "scoped under `account`" in written
