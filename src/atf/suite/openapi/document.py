"""One OpenAPI document: fetching it, and reading the shapes out of it."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

DEFAULT_TIMEOUT = 30.0

Fragment = Mapping[str, Any]


DEFAULT_TIMEOUT = 30.0

_TYPE_NAME_OK = re.compile(r"^[a-z][a-z0-9_]*$")

# What a paginated listing calls the page of records, so the item schema can be found underneath it.
ENVELOPES = ("results", "items", "data", "records", "entries")

# How deep a `$ref` chain is followed before it is assumed to be circular.
MAX_DEPTH = 12

# An OpenAPI document is untyped data. Every fragment of it is whatever the file happened to hold
# until one of the readers below has checked it, and saying so is more honest than a `Mapping`
# annotation the document never promised.
Fragment = Any

class SchemaError(Exception):
    """The schema could not be read, or is not one a catalog could be written from."""

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
