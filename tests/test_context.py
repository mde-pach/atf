"""The scratchpad, and what it can say about what it is holding.

A scenario's own use of the context is scenarios: a `When` writes to `result`, a claim reads it back,
and `specs/features/claims.feature` says what happens when it is asked for a slot nothing has put
there. What is here is the layer below that — the *descriptions*.

`Context` behaves as the namespace it replaced and additionally keeps a description of everything
set on it: how many records, which fields they share, which resource type they look like. Those
descriptions reach the run history and the cockpit, so they are observable second-hand, and every
rule about them is a decision over one value: a list of records is described by the fields they
*share*, an underscore is ATF's own bookkeeping and is not described, a description never holds the
value because a record carries a token as readily as a title, and a type is guessed only when
exactly one fits — because a wrong label is worse than none.

None of that is a behaviour a spec could name. It is a table of value-in, sentence-out.
"""


from __future__ import annotations

import pytest

from atf.spec.context import BOOLEAN, NOTHING, NUMBER, RECORD, RECORDS, TEXT, Context, describe, ephemeral_record

# ---- it is still the namespace every existing step was written against ------


def test_attributes_are_set_read_and_deleted_as_before():
    context = Context()
    context.result = 3
    assert context.result == 3
    del context.result
    with pytest.raises(AttributeError):
        _ = context.result


def test_an_attribute_never_set_raises_attribute_error():
    with pytest.raises(AttributeError):
        _ = Context().nothing_here


def test_initial_values_can_be_passed_in():
    context = Context(account={"id": 1})
    assert context.account == {"id": 1}
    assert context.slots["account"].kind == RECORD


def test_two_contexts_holding_the_same_things_are_equal():
    assert Context(a=1) == Context(a=1)
    assert Context(a=1) != Context(a=2)
    assert Context(a=1) != {"a": 1}


def test_repr_shows_what_is_held():
    assert repr(Context(plan="standard")) == "Context(plan='standard')"


# ---- what it remembers ------------------------------------------------------


def test_a_record_is_described_by_the_fields_it_carries():
    context = Context()
    context.result = {"id": 7, "title": "Buy milk", "done": False}
    slot = context.slots["result"]
    assert slot.kind == RECORD
    assert slot.fields == ["done", "id", "title"]
    assert slot.count == 1


def test_a_list_of_records_is_described_by_the_fields_they_share():
    context = Context()
    context.result = [{"id": 1, "title": "a", "extra": 1}, {"id": 2, "title": "b"}]
    slot = context.slots["result"]
    assert slot.kind == RECORDS
    assert slot.count == 2
    assert slot.fields == ["id", "title"], "a field only one record has cannot be asserted on"


@pytest.mark.parametrize(
    "value,kind",
    [("standard", TEXT), (3, NUMBER), (3.5, NUMBER), (True, BOOLEAN), (None, NOTHING)],
)
def test_plain_values_are_described_by_kind(value, kind):
    context = Context()
    context.result = value
    assert context.slots["result"].kind == kind


def test_a_description_never_holds_the_value():
    """Slots leave this process and land in run history; a record can carry a token."""
    context = Context()
    context.result = {"password": "hunter2"}
    assert "hunter2" not in repr(context.slots["result"])
    assert "hunter2" not in str(context.slots["result"].as_dict())
    assert context.slots["result"].fields == ["password"]


def test_atf_bookkeeping_is_not_described():
    context = Context()
    context._ephemeral = [("visitors.walkin", {"id": 1})]
    assert context.slots == {}
    assert context.values == {}


def test_deleting_an_attribute_forgets_its_slot():
    context = Context()
    context.result = 1
    del context.result
    assert context.slots == {}


# ---- guessing which resource type a record looks like -----------------------


def test_a_record_is_recognised_when_exactly_one_type_fits():
    context = Context(recognise=lambda record: "task" if "uuid" in record else "")
    context.result = [{"uuid": 1, "title": "a"}]
    slot = context.slots["result"]
    assert slot.resource_type == "task"
    assert slot.guessed is True


def test_an_unrecognised_record_is_left_unlabelled():
    context = Context(recognise=lambda record: "")
    context.result = {"anything": 1}
    assert context.slots["result"].resource_type == ""
    assert context.slots["result"].guessed is False


def test_a_recogniser_that_raises_never_fails_the_scenario():
    def explode(record):
        raise RuntimeError("boom")

    context = Context(recognise=explode)
    context.result = {"a": 1}
    assert context.slots["result"].resource_type == ""


def test_the_provisioning_step_can_say_what_a_slot_really_is():
    """A guess is a guess; the step that provisioned the record knows, so it says so."""
    context = Context(recognise=lambda record: "")
    context.account = {"id": 1, "email": "a@b.test"}
    context.note("account", resource_type="account", node_id="accounts.primary")

    slot = context.slots["account"]
    assert slot.resource_type == "account"
    assert slot.node_id == "accounts.primary"
    assert slot.guessed is False


def test_noting_a_slot_that_does_not_exist_does_nothing():
    context = Context()
    context.note("absent", resource_type="account")
    assert context.slots == {}


# ---- how a slot reads -------------------------------------------------------


@pytest.mark.parametrize(
    "value,summary",
    [
        ([{"id": 1}, {"id": 2}], "2 records carrying id"),
        ([{"id": 1}], "1 record carrying id"),
        ({"id": 1, "done": False}, "one record carrying done, id"),
        ("standard", "some text"),
        (7, "a number"),
        (None, "nothing"),
    ],
)
def test_a_slot_summarises_itself_in_words(value, summary):
    assert describe("result", value).summary == summary


def test_a_recognised_slot_says_what_it_looks_like():
    slot = describe("result", [{"uuid": 1}], recognise=lambda record: "task")
    assert slot.summary == "1 task record carrying uuid"


# ---- the ephemeral lookup ---------------------------------------------------


def test_the_record_a_scenario_built_for_an_ephemeral_node_is_found():
    context = Context()
    context._ephemeral = [("visitors.walkin", {"id": "v1"})]
    assert ephemeral_record(context, "visitors.walkin") == {"id": "v1"}
    assert ephemeral_record(context, "visitors.other") is None


def test_the_most_recently_built_ephemeral_record_wins():
    """One scenario can provision the same ephemeral node twice; the steps mean the last one."""
    context = Context()
    context._ephemeral = [("visitors.walkin", {"id": "v1"}), ("visitors.walkin", {"id": "v2"})]
    assert ephemeral_record(context, "visitors.walkin") == {"id": "v2"}


def test_a_context_that_never_provisioned_anything_has_no_ephemeral_records():
    assert ephemeral_record(Context(), "visitors.walkin") is None
