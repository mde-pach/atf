"""`@rest(...)` — a resource an HTTP API owns."""

from __future__ import annotations

from typing import Any, TypedDict

import httpx

from ..declare import Unreachable, adapter, declaration_of, is_resource, values_of
from ..model import compare
from ..spi import Record
from . import http

SUCCESS = (200, 201, 202, 204)
ACTION_VERBS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@adapter("rest")
class Rest:
    """Resources an HTTP API owns, one client per environment."""

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
            raise ValueError("the rest system needs a `base_url`")
        self.pagination = settings.get("pagination")
        self.client = http.build_client(
            base,
            auth=settings.get("auth"),
            timeout=float(settings.get("timeout", http.DEFAULT_TIMEOUT)),
            headers=dict(settings.get("headers") or {}),
            verify=bool(settings.get("verify", True)),
        )

    # --- What a resource declared ---------------------------------------------------------------

    def _options(self, resource: Any) -> dict[str, Any]:
        return declaration_of(resource).options

    def _path(self, resource: Any) -> str:
        path = self._options(resource).get("path")
        if not path:
            raise Unreachable(f'{declaration_of(resource).kind}: no path — write it as @rest(path="/owners")')
        return str(path)

    def _id_field(self, resource: Any) -> str:
        return str(self._options(resource).get("id_field", "id"))

    def _identity(self, resource: Any) -> Record:
        values = values_of(resource)
        return {field: values[field] for field in declaration_of(resource).unique_by}

    def _body(self, resource: Any) -> Record:
        """What `create` sends: the declared fields, with a parent resolved to its identifier.

        ATF hands over the parent itself; this is where it becomes whatever the body calls it.
        """
        out: Record = {}
        for field, value in values_of(resource).items():
            if is_resource(value):
                parent = self.find(value)
                if parent is None:
                    raise Unreachable(f"{field}: the resource it points at has not been made")
                out[f"{field}_id"] = parent.get(self._id_field(value))
            else:
                out[field] = value
        return out

    def _unwrap(self, payload: Any, resource: Any) -> Any:
        key = self._options(resource).get("record_key")
        return payload.get(str(key)) if key and isinstance(payload, dict) else payload

    def _matches(self, record: Record, identity: Record) -> bool:
        return all(compare.matches(record.get(field), value) for field, value in identity.items())

    # --- The SPI --------------------------------------------------------------------------------

    def find(self, resource: Any) -> Record | None:
        identity = self._identity(resource)
        if not identity:
            raise Unreachable(f"{declaration_of(resource).kind}: no unique_by, so nothing says which one it is")
        try:
            return self._by_path(resource, identity) or self._by_listing(resource, identity)
        except (httpx.HTTPError, ValueError) as exc:
            # A shape the adapter cannot read is the same kind of answer as a connection refused:
            # the question could not be asked, so it travels through the SPI's own channel.
            raise Unreachable(f"{self._path(resource)}: {exc}") from exc

    def _by_path(self, resource: Any, identity: Record) -> Record | None:
        """The `path` strategy: the recognised value is the address."""
        template = self._options(resource).get("read_path")
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

    def _by_listing(self, resource: Any, identity: Record) -> Record | None:
        """The `filter` strategy when the API takes the fields as parameters, `scan` when it does not."""
        wanted = [str(name) for name in self._options(resource).get("list_filter") or []]
        params = {name: identity[name] for name in wanted if name in identity}
        records = self._collection(resource, params)
        return next((record for record in records if self._matches(record, identity)), None)

    def _collection(self, resource: Any, params: Record | None = None) -> list[Record]:
        """A whole collection, however this API wraps and pages it.

        `collection_key` unwraps a list; `record_key` unwraps one record.
        """
        url = self._path(resource)
        key = self._options(resource).get("collection_key")
        if key and not self.pagination:
            response = self.client.get(url, params=dict(params or {}))
            if response.status_code not in SUCCESS:
                raise Unreachable(f"{url} answered {response.status_code}")
            inside = response.json().get(str(key)) if isinstance(response.json(), dict) else None
            if not isinstance(inside, list):
                raise Unreachable(f"{url}: no {key!r} list in the answer")
            return [row for row in inside if isinstance(row, dict)]
        return http.list_records(self.client, url, params=dict(params or {}), pagination=self.pagination)

    def create(self, resource: Any) -> Record:
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

    def update(self, resource: Any, found: Record, changes: Record) -> Record:
        url = f"{self._path(resource)}/{found[self._id_field(resource)]}"
        response = self.client.patch(url, json=changes)
        if response.status_code not in SUCCESS:
            raise Unreachable(f"{url} answered {response.status_code}: {response.text[:200]}")
        after = self._unwrap(response.json(), resource) if response.content else None
        return after if isinstance(after, dict) and after else {**found, **changes}

    def delete(self, resource: Any, found: Record) -> None:
        url = f"{self._path(resource)}/{found[self._id_field(resource)]}"
        response = self.client.delete(url)
        if response.status_code not in (*SUCCESS, 404):
            raise Unreachable(f"{url} answered {response.status_code}")

    def act(self, resource: Any, found: Record, action: Any) -> Record | None:
        """A declared verb: `PATCH` the fields the action names onto this record."""
        url = f"{self._path(resource)}/{found[self._id_field(resource)]}"
        response = self.client.patch(url, json=dict(getattr(action, "values", {})))
        if response.status_code not in SUCCESS:
            raise Unreachable(f"{url} answered {response.status_code}: {response.text[:200]}")
        after = self._unwrap(response.json(), resource) if response.content else None
        return after if isinstance(after, dict) else None

    def browse(self, resource: Any) -> list[Record]:
        try:
            return self._collection(resource)
        except (httpx.HTTPError, ValueError) as exc:
            raise Unreachable(f"{self._path(resource)}: {exc}") from exc

    def close(self) -> None:
        self.client.close()
