"""`Record` — a record an HTTP API owns, over the `http` driver."""

from __future__ import annotations

from typing import Any, ClassVar, TypedDict

import httpx
from typing_extensions import override

from ..declare import (
    Driver,
    DriverProperty,
    Resource,
    Unreachable,
    declaration_of,
    instance_of,
    is_resource,
    register_system,
)
from ..model import compare
from ..spi import Payload
from . import http

SUCCESS = (200, 201, 202, 204)


class Http(Driver):
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


class Record(Resource):
    """One record an HTTP API owns."""

    #: The collection this kind lives at, as `at=` wrote it. Rest's own setting, not ATF's — read
    #: from the class alone, since building a URL needs it before any instance exists.
    at: ClassVar[str] = ""
    http = DriverProperty[Http]("http")
    #: What this API calls the identifier. Read for lineage and for `update`/`delete`.
    id_field: ClassVar[str] = "id"
    #: What a column holding a parent is called: `owner` becomes `owner_id`.
    parent_suffix: ClassVar[str] = "_id"

    def __init_subclass__(cls, *, at: str = "", **rest: Any) -> None:
        if at:
            cls.at = at
        super().__init_subclass__(**rest)

    @classmethod
    def _path(cls) -> str:
        if not cls.at:
            raise Unreachable(
                f'{cls.__name__}: no path — write it as `class {cls.__name__}(Record, at="/owners")`'
            )
        return cls.at

    def _identity(self) -> Payload:
        return {name: getattr(self, name) for name in declaration_of(self).key}

    def _body(self) -> Payload:
        """What `create` sends: the declared fields, with a parent resolved to its identifier.

        ATF hands over the parent itself; this is where it becomes whatever the body calls it.
        """
        out: Payload = {}
        suffix = type(self).parent_suffix
        for field, value in instance_of(self).values.items():
            if not is_resource(value):
                out[field] = value
                continue
            # A parent with no identity yet is a lineage edge and nothing more: it had to exist
            # first, and the system that made it has no identifier to send.
            identity = instance_of(value).identity
            if identity is not None:
                out[f"{field}{suffix}"] = identity
        return out

    def _matches(self, record: Payload, identity: Payload) -> bool:
        return all(compare.matches(record.get(field), value) for field, value in identity.items())

    def _collection(self, params: Payload | None = None) -> list[Payload]:
        return http.list_records(
            self.http.client, type(self)._path(), params=dict(params or {}), pagination=self.http.pagination
        )

    # --- The SPI --------------------------------------------------------------------------------

    @override
    def find(self) -> Payload | None:
        """The default: a bare-array `GET`, filtered by the `Key` fields as query parameters.

        An API shaped differently — a templated single-record read, a wrapped response — overrides
        this directly, next to the declaration it belongs to.
        """
        identity = self._identity()
        if not identity:
            raise Unreachable(
                f"{type(self).__name__}: the http system cannot tell one of these apart. An HTTP "
                f"API has no schema to read, so mark the field: `email: Record.Key[str]`"
            )
        try:
            records = self._collection(identity)
            return next((record for record in records if self._matches(record, identity)), None)
        except (httpx.HTTPError, ValueError) as exc:
            raise Unreachable(f"{type(self)._path()}: {exc}") from exc

    @override
    def create(self) -> Payload:
        url = type(self)._path()
        response = self.http.client.post(url, json=self._body())
        if response.status_code not in SUCCESS:
            raise Unreachable(f"{url} answered {response.status_code}: {response.text[:200]}")
        made = response.json() if response.content else None
        if isinstance(made, dict) and made:
            return made
        # No identity in the answer — a 204. Re-read it.
        found = self.find()
        if found is None:
            raise Unreachable(f"{url}: created, and not findable afterwards")
        return found

    @override
    def update(self, changes: Payload) -> Payload:
        found = self.find()
        if found is None:
            raise Unreachable(f"{type(self)._path()}: updating a record that is not there")
        url = f"{type(self)._path()}/{found[type(self).id_field]}"
        response = self.http.client.patch(url, json=changes)
        if response.status_code not in SUCCESS:
            raise Unreachable(f"{url} answered {response.status_code}: {response.text[:200]}")
        after = response.json() if response.content else None
        return after if isinstance(after, dict) and after else {**found, **changes}

    @override
    def delete(self) -> None:
        found = self.find()
        if found is None:
            return
        url = f"{type(self)._path()}/{found[type(self).id_field]}"
        response = self.http.client.delete(url)
        if response.status_code not in (*SUCCESS, 404):
            raise Unreachable(f"{url} answered {response.status_code}")

    def browse(self) -> list[Payload]:
        try:
            return self._collection()
        except (httpx.HTTPError, ValueError) as exc:
            raise Unreachable(f"{type(self)._path()}: {exc}") from exc


register_system(Record, Http, "record")
