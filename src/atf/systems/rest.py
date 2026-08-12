"""`@record(...)` — a record an HTTP API owns, over the `http` driver."""

from __future__ import annotations

from typing import Any, TypedDict

import httpx

from ..declare import Unreachable, adapter, driver
from ..model import compare
from ..spi import Record, Resource
from . import http

SUCCESS = (200, 201, 202, 204)
ACTION_VERBS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@driver("http")
class Http:
    """One HTTP client, pointed at one API. A step asks for this by the name `http`."""

    class Settings(TypedDict, total=False):
        """What an environment configures."""

        base_url: str
        auth: Any
        headers: dict[str, str]
        timeout: float
        verify: bool
        pagination: dict[str, Any]

    def __init__(self, settings: Settings) -> None:
        base = str(settings.get("base_url", ""))
        if not base:
            raise ValueError("the http driver needs a `base_url`")
        self.pagination = settings.get("pagination")
        self.client = http.build_client(
            base,
            auth=settings.get("auth"),
            timeout=float(settings.get("timeout", http.DEFAULT_TIMEOUT)),
            headers=dict(settings.get("headers") or {}),
            verify=bool(settings.get("verify", True)),
        )


@adapter("record", driver="http")
class ApiRecord:
    """One record an HTTP API owns."""

    class Options(TypedDict, total=False):
        """What the decorator takes, per resource."""

        path: str
        #: A templated read for the `path` strategy: `/owners/{email}`.
        read_path: str
        #: Recognition fields the API accepts as query parameters, for the `filter` strategy.
        list_filter: list[str]
        #: The key one record is wrapped in, when the API wraps it.
        record_key: str
        #: The key a *collection* is wrapped in, for an API answering `{"items": [...]}` to a list.
        collection_key: str
        #: What this API calls the identifier. Read for lineage and for `delete`.
        id_field: str
        #: What tells one of these apart. An HTTP API has no schema to read, so it is said here.
        known_by: list[str]

    def recognises(self, resource: Resource) -> tuple[str, ...]:
        """What tells one of these apart.

        Read off `known_by` on the decorator, which is where a system with no schema takes it.
        """
        written = resource.options.get("known_by")
        return tuple(str(one) for one in written) if written else ()

    def __init__(self, http: Http) -> None:
        self.client = http.client
        self.pagination = http.pagination

    # --- What a resource declared ---------------------------------------------------------------

    def _id_field(self, resource: Resource) -> str:
        return str(resource.options.get("id_field", "id"))

    def _suffix(self, resource: Resource) -> str:
        return str(resource.options.get("parent_suffix", "_id"))

    def _path(self, resource: Resource) -> str:
        path = resource.options.get("path")
        if not path:
            raise Unreachable(f'{resource.kind}: no path — write it as @record(path="/owners")')
        return str(path)

    def _identity(self, resource: Resource) -> Record:
        return dict(resource.identity)

    def _body(self, resource: Resource) -> Record:
        """What `create` sends: the declared fields, with a parent resolved to its identifier.

        ATF hands over the parent itself; this is where it becomes whatever the body calls it.
        """
        out: Record = dict(resource.values)
        suffix = self._suffix(resource)
        for field, parent in resource.parents.items():
            # A parent with no key is a lineage edge and nothing more: it had to exist first, and
            # the system that made it has no identifier to send.
            if parent.key is not None:
                out[f"{field}{suffix}"] = parent.key
        return out

    def _unwrap(self, payload: Any, resource: Resource) -> Any:
        key = resource.options.get("record_key")
        return payload.get(str(key)) if key and isinstance(payload, dict) else payload

    def _matches(self, record: Record, identity: Record) -> bool:
        return all(compare.matches(record.get(field), value) for field, value in identity.items())

    # --- The SPI --------------------------------------------------------------------------------

    def find(self, resource: Resource) -> Record | None:
        identity = self._identity(resource)
        if not identity:
            raise Unreachable(
                f"{resource.kind}: the http system cannot tell one of these apart. An HTTP API has "
                f"no schema to read, so name the fields on the decorator: "
                f'@http.record(path="...", known_by=["email"])'
            )
        try:
            return self._by_path(resource, identity) or self._by_listing(resource, identity)
        except (httpx.HTTPError, ValueError) as exc:
            # A shape the adapter cannot read is the same kind of answer as a connection refused:
            # the question could not be asked, so it travels through the SPI's own channel.
            raise Unreachable(f"{self._path(resource)}: {exc}") from exc

    def _by_path(self, resource: Resource, identity: Record) -> Record | None:
        """The `path` strategy: the recognised value is the address."""
        template = resource.options.get("read_path")
        if not template:
            return None
        url = str(template).format(**identity)
        response = self.client.get(url)
        if response.status_code == 404:
            return None
        if response.status_code not in SUCCESS:
            raise Unreachable(f"{url} answered {response.status_code}")
        found = self._unwrap(response.json(), resource)
        return found if isinstance(found, dict) else None

    def _by_listing(self, resource: Resource, identity: Record) -> Record | None:
        """The `filter` strategy when the API takes the fields as parameters, `scan` when it does not."""
        wanted = [str(name) for name in resource.options.get("list_filter") or []]
        params = {name: identity[name] for name in wanted if name in identity}
        records = self._collection(resource, params)
        return next((record for record in records if self._matches(record, identity)), None)

    def _collection(self, resource: Resource, params: Record | None = None) -> list[Record]:
        """A whole collection, however this API wraps and pages it.

        `collection_key` unwraps a list; `record_key` unwraps one record.
        """
        url = self._path(resource)
        key = resource.options.get("collection_key")
        if key and not self.pagination:
            response = self.client.get(url, params=dict(params or {}))
            if response.status_code not in SUCCESS:
                raise Unreachable(f"{url} answered {response.status_code}")
            inside = response.json().get(str(key)) if isinstance(response.json(), dict) else None
            if not isinstance(inside, list):
                raise Unreachable(f"{url}: no {key!r} list in the answer")
            return [row for row in inside if isinstance(row, dict)]
        return http.list_records(self.client, url, params=dict(params or {}), pagination=self.pagination)

    def create(self, resource: Resource) -> Record:
        url = self._path(resource)
        response = self.client.post(url, json=self._body(resource))
        if response.status_code not in SUCCESS:
            raise Unreachable(f"{url} answered {response.status_code}: {response.text[:200]}")
        made = self._unwrap(response.json(), resource) if response.content else None
        if isinstance(made, dict) and made:
            return made
        # No identity in the answer — a 204, or an envelope this adapter does not know. Re-read it.
        found = self.find(resource)
        if found is None:
            raise Unreachable(f"{url}: created, and not findable afterwards")
        return found

    def update(self, resource: Resource, found: Record, changes: Record) -> Record:
        url = f"{self._path(resource)}/{found[self._id_field(resource)]}"
        response = self.client.patch(url, json=changes)
        if response.status_code not in SUCCESS:
            raise Unreachable(f"{url} answered {response.status_code}: {response.text[:200]}")
        after = self._unwrap(response.json(), resource) if response.content else None
        return after if isinstance(after, dict) and after else {**found, **changes}

    def delete(self, resource: Resource, found: Record) -> None:
        url = f"{self._path(resource)}/{found[self._id_field(resource)]}"
        response = self.client.delete(url)
        if response.status_code not in (*SUCCESS, 404):
            raise Unreachable(f"{url} answered {response.status_code}")

    def browse(self, resource: Resource) -> list[Record]:
        try:
            return self._collection(resource)
        except (httpx.HTTPError, ValueError) as exc:
            raise Unreachable(f"{self._path(resource)}: {exc}") from exc

    def close(self) -> None:
        self.client.close()
