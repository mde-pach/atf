"""Everything ATF's own steps say, and what each of them claims. Import-safe: no pytest in here."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..model.compare import is_empty, written_contains, written_matches
from .context import RESULT
from .patterns import PROVISION, PROVISION_FRESH, PROVISION_FRESH_VARIED, PROVISION_VARIED

EXISTS = 'the {resource_type} "{name}" exists'

GONE = 'the {resource_type} "{name}" is gone'

FIELD_IS = 'the {resource_type} "{name}" field "{field}" is "{value}"'

FIELD_IS_NOT = 'the {resource_type} "{name}" field "{field}" is not "{value}"'

FIELD_CONTAINS = 'the {resource_type} "{name}" field "{field}" contains "{value}"'

FIELD_LACKS = 'the {resource_type} "{name}" field "{field}" does not contain "{value}"'

FIELD_EMPTY = 'the {resource_type} "{name}" field "{field}" is empty'

FIELD_NOT_EMPTY = 'the {resource_type} "{name}" field "{field}" is not empty'

# How many of a type an environment holds. The one claim about a resource *type*: "nothing was
# created the second time" is a claim about a population, with no one resource to name.
COUNT = "the environment has {count:d} {resource_type}"

# Whole-shape claims. A record has a shape, and checking it a field at a time costs a line each and
# says nothing about the record as a whole. A table says the shape in one claim, and a `#marker`
# says what *kind* of thing a field must hold where the value itself is not the point — an id the
# backend assigned, a timestamp that was `now`.
SHAPE_IS = 'the {resource_type} "{name}" is:'

SLOT_SHAPE_IS = "the {slot:w} is:"

# The generic `When`. Until this existed the framework could *read* a system and never act on one:
# `find` and `create` were reachable from Gherkin, `delete` and `browse` from nothing at all, and
# every action a project needed was hand-written — including the ones the adapter already knew how
# to perform. An adapter offers mechanical verbs, the catalog names a domain action in terms of
# them, and this says the domain action.
#
# `{action:w}` is one word — an action is a name the catalog chose. That is also what keeps this from
# swallowing a project's own `When`: `I list the projects of the account` names no instance in
# quotes, and `I run "atf seed local"` has no ` the ` in it.
ACT = 'I {action:w} the {resource_type} "{name}"'

LIST_EVERY = "I list every {resource_type}"

# Running a command, said the way a person writes one: the command line is the whole of it. What
# came back lands on `result`, so every claim already in this module applies to it.
RUN = 'I run "{command}"'

# The four claims about what a step produced name the slot they are about, so a scenario with two
# actions can compare either of them.
#
# `{slot:w}` is letters, numbers and underscore — no spaces, no quotes. That is what keeps these
# patterns from also matching `the todo_list "groceries" field "owner_id" is "…"`: a resource claim
# always names its instance between quotes, and a slot claim never does.
SLOT_CONTAINS = 'the {slot:w} contains the {resource_type} "{name}"'

SLOT_LACKS = 'the {slot:w} does not contain the {resource_type} "{name}"'

SLOT_FIELD_IS = 'the {slot:w} field "{field}" is "{value}"'

SLOT_FIELD_IS_NOT = 'the {slot:w} field "{field}" is not "{value}"'

SLOT_FIELD_CONTAINS = 'the {slot:w} field "{field}" contains "{value}"'

SLOT_FIELD_LACKS = 'the {slot:w} field "{field}" does not contain "{value}"'

SLOT_FIELD_EMPTY = 'the {slot:w} field "{field}" is empty'

SLOT_FIELD_NOT_EMPTY = 'the {slot:w} field "{field}" is not empty'

# A capture's parameter name is also what it means, ATF having chosen both. Only the patterns in
# this table are read that way: a project's step may have a `field` that means something else.
TYPE, NAME, FIELD, VALUE, SLOT, COUNT_OF = "resource_type", "name", "field", "value", "slot", "count"

ACTION, COMMAND = "action", "command"

# How many records a count claim will read before it gives up. A listing that hits the cap is
# reported, never counted: a number that might be the cap is not an answer.
LISTING_LIMIT = 1000

@dataclass(frozen=True)
class GenericStep:
    """One step ATF itself defines, and what its parameters mean."""

    keyword: str
    pattern: str
    summary: str
    captures: tuple[str, ...]
    # What the step reads from the context, declared: these reach it through `getattr`, and an
    # attribute name is all source analysis can see.
    needs: tuple[str, ...] = ()
    # What it writes to the context, declared for the same reason: their decorators name a constant,
    # so nothing reading the source can pair a wording with what it does.
    produces: tuple[str, ...] = ()
    # Whether the step reads the slot it names, and not a slot fixed in advance. Nothing can be
    # listed in `needs` for these — which slot they need is a choice the author has not made yet —
    # so what an interface checks is that the slot they *did* name is one the scenario holds.
    needs_slot: bool = False
    # Whether the step carries a table under it. A picker that offers one has offered a line it
    # cannot finish, so it does not offer them — they are written by hand, or in text mode.
    takes_table: bool = False

GENERIC_STEPS: tuple[GenericStep, ...] = (
    GenericStep(
        "given",
        PROVISION,
        "Make this resource exist here, and everything it depends on first.",
        (TYPE, NAME),
    ),
    GenericStep(
        "given",
        PROVISION_VARIED,
        "The same, with some of its body written differently for this scenario only.",
        (TYPE, NAME),
        takes_table=True,
    ),
    GenericStep(
        "given",
        PROVISION_FRESH,
        "Make one of these that belongs to this scenario alone, and goes when it does.",
        (TYPE, NAME),
    ),
    GenericStep(
        "given",
        PROVISION_FRESH_VARIED,
        "The same, with some of its body written differently for this scenario only.",
        (TYPE, NAME),
        takes_table=True,
    ),
    GenericStep(
        "when",
        ACT,
        "Do to this resource what its type says that action means.",
        (ACTION, TYPE, NAME),
        produces=(RESULT,),
    ),
    GenericStep(
        "when",
        RUN,
        "Run a command line, and keep what it said.",
        (COMMAND,),
        produces=(RESULT,),
    ),
    GenericStep(
        "when",
        LIST_EVERY,
        "Read back every resource of this type the environment holds.",
        (TYPE,),
        produces=(RESULT,),
    ),
    GenericStep(
        "then",
        EXISTS,
        "Read this resource back from the environment and require it to be there.",
        (TYPE, NAME),
    ),
    GenericStep(
        "then",
        GONE,
        "Read this resource back and require it to be absent — what a deletion is checked with.",
        (TYPE, NAME),
    ),
    GenericStep(
        "then",
        FIELD_IS,
        "Read this resource back and compare one of its fields with a value.",
        (TYPE, NAME, FIELD, VALUE),
    ),
    GenericStep(
        "then",
        FIELD_IS_NOT,
        "Read this resource back and require one of its fields to differ from a value.",
        (TYPE, NAME, FIELD, VALUE),
    ),
    GenericStep(
        "then",
        FIELD_CONTAINS,
        "Read this resource back and require one of its fields to hold a value.",
        (TYPE, NAME, FIELD, VALUE),
    ),
    GenericStep(
        "then",
        FIELD_LACKS,
        "Read this resource back and require one of its fields not to hold a value.",
        (TYPE, NAME, FIELD, VALUE),
    ),
    GenericStep(
        "then",
        FIELD_EMPTY,
        "Read this resource back and require one of its fields to hold nothing.",
        (TYPE, NAME, FIELD),
    ),
    GenericStep(
        "then",
        FIELD_NOT_EMPTY,
        "Read this resource back and require one of its fields to hold something.",
        (TYPE, NAME, FIELD),
    ),
    GenericStep(
        "then",
        COUNT,
        "Count what this environment holds of a resource type.",
        (COUNT_OF, TYPE),
    ),
    GenericStep(
        "then",
        SHAPE_IS,
        "Read this resource back and compare a whole table of its fields at once.",
        (TYPE, NAME),
        takes_table=True,
    ),
    GenericStep(
        "then",
        SLOT_CONTAINS,
        "Require the records a step put on the context to include this resource.",
        (SLOT, TYPE, NAME),
        needs_slot=True,
    ),
    GenericStep(
        "then",
        SLOT_LACKS,
        "Require the records a step put on the context not to include this resource.",
        (SLOT, TYPE, NAME),
        needs_slot=True,
    ),
    GenericStep(
        "then",
        SLOT_FIELD_IS,
        "Compare one field of what a step put on the context with a value.",
        (SLOT, FIELD, VALUE),
        needs_slot=True,
    ),
    GenericStep(
        "then",
        SLOT_FIELD_IS_NOT,
        "Require one field of what a step put on the context to differ from a value.",
        (SLOT, FIELD, VALUE),
        needs_slot=True,
    ),
    GenericStep(
        "then",
        SLOT_FIELD_CONTAINS,
        "Require one field of what a step put on the context to hold a value.",
        (SLOT, FIELD, VALUE),
        needs_slot=True,
    ),
    GenericStep(
        "then",
        SLOT_FIELD_LACKS,
        "Require one field of what a step put on the context not to hold a value.",
        (SLOT, FIELD, VALUE),
        needs_slot=True,
    ),
    GenericStep(
        "then",
        SLOT_FIELD_EMPTY,
        "Require one field of what a step put on the context to hold nothing.",
        (SLOT, FIELD),
        needs_slot=True,
    ),
    GenericStep(
        "then",
        SLOT_FIELD_NOT_EMPTY,
        "Require one field of what a step put on the context to hold something.",
        (SLOT, FIELD),
        needs_slot=True,
    ),
    GenericStep(
        "then",
        SLOT_SHAPE_IS,
        "Compare a whole table of fields against what a step put on the context.",
        (SLOT,),
        needs_slot=True,
        takes_table=True,
    ),
)

_BY_PATTERN = {step.pattern: step for step in GENERIC_STEPS}

def generic(pattern: str) -> GenericStep | None:
    """The entry for a step ATF defines, or `None` for one the project defines."""
    return _BY_PATTERN.get(pattern)

RESOURCE, SLOT_OF, TYPE_OF = "resource", "slot", "type"

@dataclass(frozen=True)
class Comparison:
    """One claim an assertion can make, and the wording ATF writes for it."""

    key: str
    label: str
    pattern: str
    # What the claim is about: a resource in the catalog, a slot a step above put on the context,
    # or a whole resource type — which is what a claim about how many there are has to be about.
    subject: str
    # Whether it names a field of that subject, and what it is compared against.
    field: bool = False
    target: str = ""  # "" | "value" | "resource"
    # Which of the pattern's captures the target is written into. Every claim compared against a
    # written value uses `value`; a count writes a number, and `value` in the spec text would read as
    # a value the resource holds, not as how many there are.
    value_capture: str = VALUE
    # How the claim is decided, for the ones about a field. `negated` pairs each with its opposite:
    # "is not" is "is", answered the other way round.
    holds: Callable[[Any, str], bool] | None = None
    negated: bool = False
    # What a failure says after "… is <what it holds>,". `{expected}` is the written value described,
    # `{written}` the raw text of it.
    otherwise: str = ""

def _matches(actual: Any, written: str) -> bool:
    return written_matches(actual, written)

def _holds(actual: Any, written: str) -> bool:
    return written_contains(actual, written)

def _empty(actual: Any, written: str) -> bool:
    return is_empty(actual)

# What a failure says after "… is <what it holds>,". `{expected}` is the written value described,
# `{written}` the raw text of it.
NOT_THAT = "not {expected}"

MUST_NOT_BE = "which is what it must not be"

DOES_NOT_HOLD = "which does not hold {written!r}"

DOES_HOLD = "which holds {written!r}"

NOT_EMPTY_SAID = "not empty"

IS_EMPTY_SAID = "which is empty"

COMPARISONS: tuple[Comparison, ...] = (
    Comparison("exists", "exists", EXISTS, RESOURCE),
    Comparison("gone", "is gone", GONE, RESOURCE),
    Comparison("is", "is", FIELD_IS, RESOURCE, True, "value", holds=_matches, otherwise=NOT_THAT),
    Comparison(
        "is-not", "is not", FIELD_IS_NOT, RESOURCE, True, "value",
        holds=_matches, negated=True, otherwise=MUST_NOT_BE,
    ),
    Comparison(
        "holds", "contains", FIELD_CONTAINS, RESOURCE, True, "value", holds=_holds, otherwise=DOES_NOT_HOLD
    ),
    Comparison(
        "holds-not", "does not contain", FIELD_LACKS, RESOURCE, True, "value",
        holds=_holds, negated=True, otherwise=DOES_HOLD,
    ),
    Comparison("empty", "is empty", FIELD_EMPTY, RESOURCE, True, holds=_empty, otherwise=NOT_EMPTY_SAID),
    Comparison(
        "not-empty", "is not empty", FIELD_NOT_EMPTY, RESOURCE, True,
        holds=_empty, negated=True, otherwise=IS_EMPTY_SAID,
    ),
    Comparison("contains", "contains", SLOT_CONTAINS, SLOT_OF, target="resource"),
    Comparison("lacks", "does not contain", SLOT_LACKS, SLOT_OF, target="resource"),
    Comparison("result-is", "is", SLOT_FIELD_IS, SLOT_OF, True, "value", holds=_matches, otherwise=NOT_THAT),
    Comparison(
        "result-is-not", "is not", SLOT_FIELD_IS_NOT, SLOT_OF, True, "value",
        holds=_matches, negated=True, otherwise=MUST_NOT_BE,
    ),
    Comparison(
        "result-holds", "contains", SLOT_FIELD_CONTAINS, SLOT_OF, True, "value",
        holds=_holds, otherwise=DOES_NOT_HOLD,
    ),
    Comparison(
        "result-holds-not", "does not contain", SLOT_FIELD_LACKS, SLOT_OF, True, "value",
        holds=_holds, negated=True, otherwise=DOES_HOLD,
    ),
    Comparison("result-empty", "is empty", SLOT_FIELD_EMPTY, SLOT_OF, True, holds=_empty, otherwise=NOT_EMPTY_SAID),
    Comparison(
        "result-not-empty", "is not empty", SLOT_FIELD_NOT_EMPTY, SLOT_OF, True,
        holds=_empty, negated=True, otherwise=IS_EMPTY_SAID,
    ),
    Comparison("count", "how many there are", COUNT, TYPE_OF, target="value", value_capture=COUNT_OF),
)

_BY_KEY = {item.key: item for item in COMPARISONS}

_BY_CLAIM = {item.pattern: item for item in COMPARISONS}

def comparison(key: str) -> Comparison | None:
    return _BY_KEY.get(key)

def claim_of(pattern: str) -> Comparison | None:
    """The claim a generic pattern makes, so a written scenario reads back into the same choices."""
    return _BY_CLAIM.get(pattern)

def comparisons_for(subject: str, on_field: bool) -> list[Comparison]:
    """What can be claimed about this subject — about the thing itself, or about a field of it."""
    return [
        item for item in COMPARISONS if item.subject == subject and item.field == on_field
    ]
