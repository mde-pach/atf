"""Deriving catalog resource types from an OpenAPI schema."""

from __future__ import annotations

import re
import textwrap
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..model.catalog import RESERVED_FIXTURE_NAMES, TYPES_FILE
from ..model.typespec import TypeSpec
from .authoring import diff

# Every type an OpenAPI schema describes is served over a JSON API, which is the one system ATF
# ships an adapter for out of the box. Nothing in a schema could say otherwise.
SYSTEM = "rest"

DEFAULT_TIMEOUT = 30.0

# ---- how much each signal is worth ------------------------------------------
#
# The gaps matter more than the numbers. Filtering outranks everything: it is the API stating the
# intent. Convention outranks shape: a project that has already decided beats a schema that merely
# allows. Each signal is worth more than every weaker one put together, so a stronger reason is never
# outvoted by a pile of weak ones.
#
# The margin is the weakest signal there is: one reason the runner-up lacks decides, and two fields
# with the same reasons are a tie.

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

_TYPE_NAME_OK = re.compile(r"^[a-z][a-z0-9_]*$")

# What a paginated listing calls the page of records, so the item schema can be found underneath it.
ENVELOPES = ("results", "items", "data", "records", "entries")

# How deep a `$ref` chain is followed before it is assumed to be circular.
MAX_DEPTH = 12

COMMENT_WIDTH = 94


# An OpenAPI document is untyped data. Every fragment of it is whatever the file happened to hold
# until one of the readers below has checked it, and saying so is more honest than a `Mapping`
# annotation the document never promised.
Fragment = Any


class SchemaError(Exception):
    """The schema could not be read, or is not one a catalog could be written from."""


# ---- reading one -------------------------------------------------------------


def read(source: str, headers: Mapping[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """The schema at `source`, which is a URL when it has a scheme in it and a file otherwise."""
    text = _fetched(source, headers, timeout) if is_url(source) else _opened(source)
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SchemaError(f"{source}: could not be read as JSON or YAML: {exc}") from None
    if not isinstance(document, dict) or not isinstance(document.get("paths"), dict):
        raise SchemaError(
            f"{source}: this is not an OpenAPI schema — nothing in it declares `paths`. "
            "Point the import at the schema document itself, not at the documentation page that renders it."
        )
    return document


def is_url(source: str) -> bool:
    """Whether to fetch it or open it. A scheme is the whole of the difference."""
    return "://" in source


def _opened(source: str) -> str:
    try:
        return Path(source).expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        raise SchemaError(f"{source}: {exc.strerror or exc}") from None


def _fetched(source: str, headers: Mapping[str, str] | None, timeout: float) -> str:
    """One GET of a static document: no retries, no session, no pagination.

    Raises `SchemaError` naming the source when the read fails or the response is not text.
    """
    import httpx

    try:
        response = httpx.get(source, headers=dict(headers or {}), timeout=timeout, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise SchemaError(f"{source}: {exc}") from None
    if response.status_code >= 400:
        raise SchemaError(
            f"{source}: {response.status_code} {response.text[:200]}"
            + (
                "\n  The schema may need credentials. Put them under this schema's `headers:` in the "
                "manifest, as a `*_env` pointer."
                if response.status_code in {401, 403}
                else ""
            )
        )
    return response.text


def headers_for(settings: Mapping[str, Any]) -> dict[str, str]:
    """The headers a schema is fetched with, from a manifest entry whose `*_env` pointers are resolved.

    A header value is normally a string. It may instead be a `bearer` mapping, so that a token which
    must not be a literal is written the way every other token in a manifest is written:

    ```yaml
    headers: { Authorization: { bearer: { token_env: ATF_TOKEN } } }
    ```
    """
    raw = settings.get("headers") or {}
    if not isinstance(raw, Mapping):
        raise SchemaError("`headers` must be a mapping of header name to the value sent under it")

    out: dict[str, str] = {}
    for name, value in raw.items():
        if isinstance(value, str):
            out[str(name)] = value
            continue
        if isinstance(value, Mapping) and "bearer" in value:
            spec = value["bearer"]
            token = spec.get("token") if isinstance(spec, Mapping) else spec
            if not token:
                raise SchemaError(f"the header {name} says `bearer` but carries no token — use `token_env`")
            out[str(name)] = f"Bearer {token}"
            continue
        raise SchemaError(f"the header {name} is neither a string nor a `bearer` token")
    return out


# ---- what a collection in the schema says ------------------------------------


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


# ---- reading the shapes out of the document ----------------------------------


def type_name(segment: str) -> str:
    """A path segment as a catalog type name: singular, lower case, underscores.

    The singularisation is the four rules everybody knows and nothing else, so a name that comes out
    wrong is one somebody renames once, in a generated file.
    """
    stem = re.sub(r"[^a-z0-9]+", "_", segment.lower()).strip("_")
    if stem.endswith("ies") and len(stem) > 3:
        stem = stem[:-3] + "y"
    elif stem.endswith(("sses", "shes", "ches", "xes", "zes")):
        stem = stem[:-2]
    elif stem.endswith("s") and not stem.endswith("ss"):
        stem = stem[:-1]
    return stem if _TYPE_NAME_OK.match(stem) else ""


def _is_parameter(segment: str) -> bool:
    return segment.startswith("{") and segment.endswith("}")


def _parent_of(segments: list[str]) -> str:
    """The type a scoped collection hangs off: whatever the last scoping parameter came after."""
    for index in range(len(segments) - 1, -1, -1):
        if _is_parameter(segments[index]) and index > 0:
            return type_name(segments[index - 1])
    return ""


def _query_parameters(item: Fragment, get: Fragment, document: Fragment) -> frozenset[str]:
    """The names the collection listing can be narrowed by — the strongest signal there is."""
    declared = [*(item.get("parameters") or []), *(get.get("parameters") or [])]
    names: set[str] = set()
    for entry in declared:
        resolved = _deref(entry, document)
        if resolved.get("in") == "query" and isinstance(resolved.get("name"), str):
            names.add(str(resolved["name"]))
    return frozenset(names)


def _id_field(properties: Fragment, name: str) -> str:
    """The field carrying the identity, read from what the API returns."""
    for candidate in ("id", "uuid", f"{name}_id", "key"):
        if candidate in properties:
            return candidate
    return "id"


def _request_schema(operation: Fragment, document: Fragment) -> dict[str, Any]:
    body = _deref(operation.get("requestBody"), document)
    schema = _json_schema(body.get("content"), document)
    # Swagger 2 puts the body in a parameter, where OpenAPI 3 has a request body.
    if not schema:
        for entry in operation.get("parameters") or []:
            resolved = _deref(entry, document)
            if resolved.get("in") == "body":
                return _deref(resolved.get("schema"), document)
    return schema


def _response_schema(operation: Fragment, document: Fragment) -> dict[str, Any]:
    responses = operation.get("responses")
    if not isinstance(responses, Mapping):
        return {}
    for code in ("200", 200, "201", 201, "default"):
        entry = responses.get(code)
        if not isinstance(entry, Mapping):
            continue
        resolved = _deref(entry, document)
        schema = _json_schema(resolved.get("content"), document) or _deref(resolved.get("schema"), document)
        if item := _item_of(schema, document):
            return item
    return {}


def _item_of(schema: Fragment, document: Fragment) -> dict[str, Any]:
    """One record out of a listing response, whether it is a bare array or a paginated envelope."""
    if not schema:
        return {}
    if schema.get("type") == "array" or "items" in schema:
        return _deref(schema.get("items"), document)
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        for envelope in ENVELOPES:
            page = _deref(properties.get(envelope), document)
            if page.get("type") == "array" or "items" in page:
                return _deref(page.get("items"), document)
    return dict(schema)


def _json_schema(content: Fragment, document: Fragment) -> dict[str, Any]:
    if not isinstance(content, Mapping):
        return {}
    for media, entry in sorted(content.items(), key=lambda pair: str(pair[0]) != "application/json"):
        if "json" in str(media) and isinstance(entry, Mapping):
            return _deref(entry.get("schema"), document)
    return {}


def _properties(schema: Fragment, document: Fragment) -> dict[str, dict[str, Any]]:
    declared = schema.get("properties")
    if not isinstance(declared, Mapping):
        return {}
    return {str(name): _deref(value, document) for name, value in declared.items()}


def _deref(node: Fragment, document: Fragment, depth: int = 0) -> dict[str, Any]:
    """A schema fragment with local `$ref`s followed and `allOf` flattened.

    Only `#/...` pointers: an external reference means another document, and fetching whatever a
    schema points at is a decision about the network that a schema reader should not be making.
    Such a fragment reads as empty, which costs a guess and never produces a wrong one.
    """
    if not isinstance(node, Mapping) or depth > MAX_DEPTH:
        return {}
    if isinstance(ref := node.get("$ref"), str):
        target = _pointer(ref, document)
        return _deref(target, document, depth + 1) if target is not None else {}
    if isinstance(node.get("allOf"), list):
        properties: dict[str, Any] = {}
        required: list[Any] = []
        for part in [*node["allOf"], {k: v for k, v in node.items() if k != "allOf"}]:
            piece = _deref(part, document, depth + 1)
            properties.update(piece.get("properties") or {})
            required.extend(piece.get("required") or [])
        return {"type": "object", "properties": properties, "required": required}
    return dict(node)


def _pointer(ref: str, document: Fragment) -> Any:
    if not ref.startswith("#/"):
        return None
    node: Any = document
    for part in ref[2:].split("/"):
        step = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, Mapping) or step not in node:
            return None
        node = node[step]
    return node


# ---- writing it down ---------------------------------------------------------


def render(collection: Collection) -> str:
    """One resource type as the YAML a person writes by hand, each guessed key annotated."""
    lines = [f"{collection.name}:", f"  system: {SYSTEM}", f"  path: {scalar(collection.path)}"]
    if collection.scope:
        # `path` is what a create posts to and `list_path` is what a lookup fills in from the body,
        # so a scoped collection needs both to say the same thing for `find` to work at all.
        lines.append(f"  list_path: {scalar(collection.path)}")
    lines.append(f"  id_field: {collection.id_field}")

    if collection.scope and collection.parent:
        lines += comment(
            f"scoped under `{collection.parent}`, so declare each one with the {collection.parent} it "
            f"belongs to — `{collection.scope[-1]}` in the body, as a `${{...}}` reference"
        )
    guess = collection.guess
    if guess:
        lines += comment(f"guessed: {guess.because}")
        lines.append(f"  natural_key: {key_said(guess.key)}")
    else:
        lines += comment(f"no natural_key: {guess.because}.")
        lines += comment(
            "Choose one by hand. Until then this type will not provision — which is the safe half of "
            "the trade: a wrong key makes every run create another record instead."
        )
    return "\n".join(lines) + "\n"


def comment(text: str) -> list[str]:
    wrapped = textwrap.wrap(text, width=COMMENT_WIDTH) or [""]
    return [f"  # {wrapped[0]}"] + [f"  #   {line}" for line in wrapped[1:]]


def scalar(value: str) -> str:
    """A value as YAML, quoted only where it has to be — a catalog is read as much as it is loaded."""
    dumped = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True).strip()
    return dumped.removesuffix("...").strip()


def key_said(fields: tuple[str, ...]) -> str:
    if len(fields) == 1:
        return scalar(fields[0])
    return "[" + ", ".join(scalar(one) for one in fields) + "]"


def header(source: str) -> str:
    return (
        f"# Resource types derived from {source} by `atf import openapi`.\n"
        "#\n"
        "# Every `natural_key` here is a guess and says what it was guessed from — check those first,\n"
        "# because a key that does not match makes ATF create another record on every run.\n"
        "#\n"
        "# `mode` and `lifecycle` are absent on purpose. A schema does not say whether ATF may create a\n"
        "# resource or must only ever find one, so every type below takes the defaults: `mode: create`\n"
        "# and `lifecycle: persistent`. Set them yourself where that is wrong.\n"
        "#\n"
        "# Re-running the import never rewrites what is in this file. It proposes the types that are\n"
        "# missing, and reports the ones the schema no longer agrees with.\n"
    )


# ---- the proposed change -----------------------------------------------------


@dataclass
class Proposal:
    """One `resources.yaml`, before and after. Nothing here has been written."""

    path: Path
    before: str
    after: str
    first: bool = False
    added: list[Collection] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    drifted: list[str] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def changes(self) -> bool:
        return self.after != self.before

    def as_diff(self, label: str) -> str:
        return diff(self.before, self.after, label)


def propose(document: Mapping[str, Any], catalog_dir: Path, source: str = "") -> Proposal:
    """What this schema would add to a catalog, without touching it.

    The whole file text is proposed and then compared, the same way the cockpit proposes a catalog
    edit: a diff a person reads is worth more than a summary they have to trust, and it is the only
    honest way to show a change to a file that is hand-authored.
    """
    path = Path(catalog_dir) / TYPES_FILE
    before = path.read_text(encoding="utf-8") if path.is_file() else ""
    declared = _declared(before)

    found = collections(document, convention_of(declared))
    added: list[Collection] = []
    kept: list[str] = []
    drifted: list[str] = []
    skipped: list[tuple[str, str]] = []

    for collection in found:
        if collection.name in declared:
            kept.append(collection.name)
            if reason := _drift(collection, declared[collection.name]):
                drifted.append(f"{collection.name}: {reason}")
            continue
        if collection.name in RESERVED_FIXTURE_NAMES:
            why = "the name is one ATF reserves for a fixture — rename it, and add it yourself"
            skipped.append((collection.name, why))
            continue
        added.append(collection)

    blocks = [render(collection) for collection in added]
    first = not declared
    if not blocks:
        after = before
    elif first:
        after = header(source or "an OpenAPI schema") + "\n" + "\n".join(blocks)
    else:
        separator = "" if not before or before.endswith("\n\n") else ("\n" if before.endswith("\n") else "\n\n")
        after = before + separator + "\n".join(blocks)

    _must_reload(after, [collection.name for collection in added], before)
    return Proposal(
        path=path,
        before=before,
        after=after,
        first=first,
        added=added,
        kept=kept,
        drifted=drifted,
        absent=sorted(set(declared) - {collection.name for collection in found}),
        skipped=skipped,
    )


def _declared(text: str) -> dict[str, Any]:
    """The types already in the file, or nothing — a registry too broken to read is a blank page."""
    try:
        loaded = yaml.safe_load(text) if text.strip() else None
    except yaml.YAMLError:
        return {}
    return {str(name): entry for name, entry in loaded.items()} if isinstance(loaded, dict) else {}


def _drift(collection: Collection, declared: Any) -> str:
    """What the schema now says that the catalog does not — reported, never applied.

    Only the two that are actionable and unambiguous. A `path` that moved is why every lookup 404s,
    and a `natural_key` naming a field the API no longer accepts is why every run creates a copy.
    Everything else a schema and a catalog can disagree about is a decision somebody made.
    """
    if not isinstance(declared, Mapping):
        return ""
    said = declared.get("path")
    if isinstance(said, str) and said and said != collection.path:
        return f"the catalog says `{said}`, the schema says `{collection.path}`"
    keys = [
        key for key in TypeSpec.from_entry(collection.name, declared).natural_keys
        if key not in collection.scope
    ]
    if keys and collection.guess.considered:
        known = {one.field for one in collection.guess.considered}
        # Only worth saying when the schema described *some* settable fields; an empty schema
        # fragment would otherwise report every type as drifted for saying nothing at all.
        if missing := [key for key in keys if key not in known]:
            return f"it is keyed on `{missing[0]}`, which this schema does not offer on a create"
    return ""


def _must_reload(text: str, names: list[str], before: str = "") -> None:
    """Proof the proposal is loadable YAML declaring what it claims to, before anyone is shown it.

    Raises `SchemaError` naming the file, not the parse error: almost every way this fails is about
    the file being appended to — a registry written as one flow mapping has nowhere to put a block
    entry — and a reader did not write the lines a parse error would point at.
    """
    try:
        loaded = yaml.safe_load(text) if text.strip() else {}
    except yaml.YAMLError as exc:
        if before.strip():
            raise SchemaError(
                f"nothing was written: these types cannot be added to {TYPES_FILE} as it stands.\n"
                f"  It has to be a block mapping of type name to settings — one `name:` per line, "
                f"with its settings indented under it.\n  ({exc})"
            ) from None
        raise SchemaError(f"the types derived from this schema are not valid YAML: {exc}") from None
    if not isinstance(loaded, dict) or any(name not in loaded for name in names):
        raise SchemaError(f"the types derived from this schema did not survive being written into {TYPES_FILE}")
