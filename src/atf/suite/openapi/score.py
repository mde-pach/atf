"""Which field a resource type is keyed on, and how sure the schema lets anyone be."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ...model.typespec import TypeSpec
from .document import (
    Fragment,
    _id_field,
    _is_parameter,
    _parent_of,
    _properties,
    _query_parameters,
    _request_schema,
    _response_schema,
    type_name,
)

FILTERS = 50

CONVENTION = 30

CONSTRAINED = 12

REQUIRED_TEXT = 8

RESEMBLANCE = 4

MARGIN = RESEMBLANCE

# A reason nobody reads is not a reason, so a guess is explained by its two strongest signals and
# not by all of them. The rest are still in the arithmetic; they are just not worth a clause.
REASONS_SHOWN = 2

KEYISH_FORMATS = frozenset(
    {"email", "idn-email", "uuid", "hostname", "idn-hostname", "uri", "iri", "ipv4", "ipv6"}
)

TIME_FORMATS = frozenset({"date", "date-time", "time", "duration"})

RESEMBLES = frozenset({"email", "slug", "code", "key", "reference", "username", "sku", "name"})

# Free text. Long, edited, frequently duplicated, and never how anyone finds a record.
PROSE = frozenset({"description", "notes", "note", "comment", "comments", "summary", "content", "text"})

# What the backend assigns and the catalog must never declare.
IDENTITYISH = frozenset({"id", "uuid", "guid"})

# A moment in time, however it is spelled.
TIMESTAMPISH = re.compile(r"(^|_)(created|updated|modified|deleted|inserted|timestamp)(_|$)|_(at|on)$")

# Types a natural key cannot have: you cannot tell two records apart by a flag, and a number or a
# structure is either an identity the backend owns or something that changes.
UNKEYABLE = frozenset({"boolean", "integer", "number", "array", "object", "null"})

@dataclass(frozen=True)
class Signal:
    """One reason a field might be the natural key, and what that reason is worth."""

    weight: int
    said: str

@dataclass(frozen=True)
class Candidate:
    field: str
    signals: tuple[Signal, ...] = ()

    @property
    def score(self) -> int:
        return sum(signal.weight for signal in self.signals)

    @property
    def strongest(self) -> list[Signal]:
        return sorted(self.signals, key=lambda signal: -signal.weight)

    @property
    def because(self) -> str:
        return said_together([signal.said for signal in self.strongest[:REASONS_SHOWN]])

    @property
    def chiefly(self) -> str:
        """The single best reason, for listing several candidates beside one another.

        A tie is read by comparing the entries, and three clauses each makes that unreadable — the
        thing a person needs to see is what the candidates have in common, which is the top signal.
        """
        return self.strongest[0].said if self.strongest else ""

@dataclass(frozen=True)
class Guess:
    """What the natural key is, or why there is not one — never one without the other."""

    key: tuple[str, ...] = ()
    because: str = ""
    considered: tuple[Candidate, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.key)

@dataclass(frozen=True)
class Collection:
    """One resource type as the schema describes it, before any of it is written down."""

    name: str
    path: str
    id_field: str
    guess: Guess
    scope: tuple[str, ...] = ()
    parent: str = ""

def said_together(parts: list[str]) -> str:
    """Several reasons as one clause, the way a person would say them."""
    if len(parts) <= 1:
        return parts[0] if parts else ""
    return ", ".join(parts[:-1]) + ", and " + parts[-1]

def convention_of(types: Mapping[str, Any]) -> dict[str, list[str]]:
    """Which field names this project already keys resources on, and which types do it.

    Read from the catalog, so a guess corrected by hand becomes the evidence the next import scores
    on.
    """
    out: dict[str, list[str]] = {}
    for name, entry in sorted(types.items()):
        if not isinstance(entry, Mapping):
            continue
        for key in TypeSpec.from_entry(name, entry).natural_keys:
            out.setdefault(key, []).append(str(name))
    return out

def collections(document: Mapping[str, Any], convention: Mapping[str, list[str]]) -> list[Collection]:
    """Every resource type the schema describes, in a stable order, with its key already guessed."""
    paths = document.get("paths")
    if not isinstance(paths, Mapping):
        return []

    found: dict[str, Collection] = {}
    for raw, item in sorted(paths.items(), key=lambda pair: str(pair[0])):
        if not isinstance(item, Mapping):
            continue
        segments = [part for part in str(raw).split("/") if part]
        # A path ending in a parameter addresses one record, and everything about the type is
        # already said by the collection above it. Importing both would declare the type twice.
        if not segments or _is_parameter(segments[-1]):
            continue
        name = type_name(segments[-1])
        if not name or name in found:
            continue
        found[name] = _collection(name, str(raw), segments, item, document, convention)
    return list(found.values())

def _collection(
    name: str,
    raw: str,
    segments: list[str],
    item: Fragment,
    document: Fragment,
    convention: Mapping[str, list[str]],
) -> Collection:
    get = item.get("get") if isinstance(item.get("get"), Mapping) else {}
    post = item.get("post") if isinstance(item.get("post"), Mapping) else {}

    # What a create may set is what a natural key may be made of; what a read returns is where the
    # identity is. Two different schemas in most APIs, and the distinction is the point.
    settable = _properties(_request_schema(post, document), document) or _properties(
        _response_schema(get, document), document
    )
    required = frozenset(str(name) for name in (_request_schema(post, document).get("required") or []))
    returned = _properties(_response_schema(get, document), document)

    scope = tuple(part[1:-1] for part in segments[:-1] if _is_parameter(part))
    parent = _parent_of(segments)
    guess = guess_key(
        properties=settable,
        required=required,
        filters=_query_parameters(item, get, document),
        scope=scope,
        id_field=(identity := _id_field(returned or settable, name)),
        convention=convention,
        collection=raw,
    )
    return Collection(name=name, path=raw, id_field=identity, guess=guess, scope=scope, parent=parent)

def guess_key(
    properties: Mapping[str, Any],
    required: frozenset[str],
    filters: frozenset[str],
    scope: tuple[str, ...],
    id_field: str,
    convention: Mapping[str, list[str]],
    collection: str = "",
) -> Guess:
    """Which field a record of this type is recognised by, and why — or why nothing was chosen.

    A pure function over the schema and the catalog, which is what makes it re-runnable to the same
    answer and testable as a table.
    """
    # Resemblance is a guess about English, so it only speaks where nothing better can. A project
    # that has already said what it keys on must never be overruled by a word looking key-shaped.
    fallback = not convention

    ranked: list[Candidate] = []
    for name, schema in sorted(properties.items()):
        if not _could_be_a_key(name, schema, id_field, scope):
            continue
        signals: list[Signal] = []
        if name in filters:
            where = f"`GET {collection}`" if collection else "the collection"
            signals.append(Signal(FILTERS, f"{where} filters by it"))
        if users := list(convention.get(name) or []):
            signals.append(Signal(CONVENTION, _convention_said(users)))
        if (shape := str(schema.get("format") or "")) in KEYISH_FORMATS and shape:
            signals.append(Signal(CONSTRAINED, f"its format is `{shape}`"))
        elif schema.get("pattern"):
            signals.append(Signal(CONSTRAINED, "the schema constrains its shape with a pattern"))
        if name in required and _is_text(schema):
            signals.append(Signal(REQUIRED_TEXT, "it is a required string"))
        if fallback and name in RESEMBLES:
            signals.append(Signal(RESEMBLANCE, f"`{name}` reads like a key, and this catalog has no convention yet"))
        if signals:
            ranked.append(Candidate(name, tuple(signals)))

    ordered = tuple(sorted(ranked, key=lambda one: (-one.score, one.field)))
    if not ordered:
        return Guess(because="nothing in the schema says how one of these is told from another")

    leader = ordered[0]
    if len(ordered) > 1 and leader.score - ordered[1].score < MARGIN:
        tied = ", ".join(f"`{one.field}` ({one.chiefly})" for one in ordered[:3])
        return Guess(because=f"nothing was clearly ahead — considered {tied}", considered=ordered)
    return Guess(key=(*scope, leader.field), because=leader.because, considered=ordered)

def _convention_said(users: list[str]) -> str:
    if len(users) == 1:
        return f"`{users[0]}` already uses it as its key"
    named = [f"`{one}`" for one in users[:3]]
    return f"{', '.join(named[:-1])} and {named[-1]} already use it as their key"

def _could_be_a_key(name: str, schema: Mapping[str, Any], id_field: str, scope: tuple[str, ...]) -> bool:
    """Whether this field could identify a record at all — before asking how likely it is to.

    A natural key has to be settable when the record is created and stable afterwards. Everything
    ruled out here fails one of those two, and no amount of positive evidence rescues it.
    """
    lowered = name.lower()
    if lowered == id_field.lower() or lowered in IDENTITYISH:
        return False  # the identity the backend assigns, which a create cannot ask for
    if name in scope:
        return False  # already in the key: the path put it there
    if schema.get("readOnly") is True:
        return False
    declared = schema.get("type")
    kinds = {str(declared)} if isinstance(declared, str) else set()
    if isinstance(declared, list):
        kinds = {str(one) for one in declared}
    if kinds & UNKEYABLE:
        return False
    if str(schema.get("format") or "") in TIME_FORMATS or TIMESTAMPISH.search(lowered):
        return False
    return lowered not in PROSE

def _is_text(schema: Mapping[str, Any]) -> bool:
    kinds = schema.get("type")
    if isinstance(kinds, str):
        return kinds == "string"
    if isinstance(kinds, list):
        return "string" in {str(one) for one in kinds}
    return True  # an enum with no declared type is a string in every schema that writes one
