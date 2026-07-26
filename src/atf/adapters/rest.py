"""Built-in generic REST adapter: configurable get-or-create over a JSON API (§7.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from .. import http
from ..catalog import Node
from ..placeholders import Unresolved
from . import Context, Record

DEFAULT_SUCCESS = (200, 201, 202, 204)


@dataclass
class RestAdapter:
    base_url: str
    auth: dict[str, Any] | None = None
    pagination: dict[str, Any] | None = None
    timeout: float = http.DEFAULT_TIMEOUT
    retries: int = 0
    verify: bool = True
    success_codes: tuple[int, ...] = DEFAULT_SUCCESS
    headers: dict[str, str] = field(default_factory=dict)
    _client: httpx.Client | None = field(default=None, init=False, repr=False)

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> RestAdapter:
        base_url = settings.get("base_url")
        if not isinstance(base_url, str) or not base_url:
            raise ValueError("rest adapter needs a `base_url`")
        success = settings.get("success_codes") or DEFAULT_SUCCESS
        return cls(
            base_url=base_url,
            auth=dict(settings["auth"]) if isinstance(settings.get("auth"), dict) else settings.get("auth"),
            pagination=dict(settings["pagination"]) if isinstance(settings.get("pagination"), dict) else None,
            timeout=float(settings.get("timeout", http.DEFAULT_TIMEOUT)),
            retries=int(settings.get("retries", 0)),
            verify=bool(settings.get("verify", True)),
            success_codes=tuple(int(code) for code in success),
            headers=dict(settings.get("headers") or {}),
        )

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = http.build_client(
                self.base_url,
                auth=self.auth,
                timeout=self.timeout,
                headers=self.headers,
                verify=self.verify,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # ---- SPI --------------------------------------------------------------

    def find(self, node: Node, ctx: Context) -> Record | None:
        criteria = self._criteria(node, ctx)
        if criteria is None:
            return None
        url, params = self._listing(node, ctx)
        # The cache is shared across every adapter the materializer drives, so the key must
        # identify the backend too: two systems can serve the same path on different hosts.
        key = f"{self.base_url}|{url}?{sorted(params.items())}"
        records = ctx.cached(key, lambda: self._list(url, params))
        for record in records:
            if all(_matches(record.get(remote), expected) for remote, expected in criteria.items()):
                return record
        return None

    def create(self, node: Node, body: Record, ctx: Context) -> Record:
        path = self._path(node)
        response = http.request(self.client, "POST", path, retries=self.retries, json=body)
        if response.status_code not in self.success_codes:
            raise ValueError(f"POST {path}: {response.status_code} {response.text[:200]}")

        record = self._record_from(response, node)
        if record is not None and record.get(node["id_field"]) is not None:
            return record

        # No identity in the create response (204, or an envelope we don't know): re-read it.
        ctx.invalidate_cache()
        found = self.find(node, ctx)
        if found is not None:
            return found
        raise ValueError(
            f"POST {path}: created, but no record carrying {node['id_field']!r} could be read back — "
            "set `record_key` if the response wraps it, or check the natural key round-trips"
        )

    def delete(self, node: Node, record: Record, ctx: Context) -> None:
        config = node["config"]
        if config.get("deletable") is False:
            return
        identity = record.get(node["id_field"])
        if identity is None:
            return
        template = config.get("delete_path")
        path = str(template).format(**record) if template else f"{self._path(node)}/{identity}"
        response = http.request(self.client, "DELETE", path, retries=self.retries)
        if response.status_code in (404, 405, 501):
            return
        if response.status_code >= 400:
            raise ValueError(f"DELETE {path}: {response.status_code} {response.text[:200]}")

    # ---- internals --------------------------------------------------------

    def _path(self, node: Node) -> str:
        path = node["config"].get("path")
        if not isinstance(path, str) or not path:
            raise ValueError(f"{node['id']}: resource type {node['resource']!r} needs a `path`")
        return path

    def _natural_keys(self, node: Node) -> list[str]:
        keys = node["config"].get("natural_key")
        if isinstance(keys, str):
            return [keys]
        if isinstance(keys, list) and keys and all(isinstance(key, str) for key in keys):
            return [str(key) for key in keys]
        raise ValueError(f"{node['id']}: resource type {node['resource']!r} needs a `natural_key`")

    def _criteria(self, node: Node, ctx: Context) -> dict[str, Any] | None:
        """`{remote_field: expected}` to match on, or `None` when the identity can't be resolved yet."""
        keys = self._natural_keys(node)
        ref_field = node["config"].get("ref_field")
        criteria: dict[str, Any] = {}
        for key in keys:
            if key not in node["body"]:
                return None
            try:
                value = ctx.resolve(node["body"][key])
            except Unresolved:
                return None
            if value is None:
                return None
            remote = str(ref_field) if (ref_field and len(keys) == 1) else key
            criteria[remote] = value
        return criteria

    def _listing(self, node: Node, ctx: Context) -> tuple[str, dict[str, Any]]:
        config = node["config"]
        url = self._path(node)
        params: dict[str, Any] = {}

        template = config.get("list_path")
        if isinstance(template, str) and template:
            url = template.format(**self._scope(node, ctx, template))

        filters = config.get("list_filter")
        if isinstance(filters, str):
            filters = [filters]
        if isinstance(filters, list):
            for name in filters:
                key = str(name)
                if key in node["body"]:
                    try:
                        params[key] = ctx.resolve(node["body"][key])
                    except Unresolved:
                        continue
        return url, params

    def _scope(self, node: Node, ctx: Context, template: str) -> dict[str, Any]:
        import string

        fields = [name for _, name, _, _ in string.Formatter().parse(template) if name]
        scope: dict[str, Any] = {}
        for name in fields:
            if name not in node["body"]:
                raise ValueError(f"{node['id']}: list_path needs {name!r} in the node body")
            scope[name] = ctx.resolve(node["body"][name])
        return scope

    def _list(self, url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return http.list_records(self.client, url, params=params, pagination=self.pagination, retries=self.retries)

    def _record_from(self, response: httpx.Response, node: Node) -> Record | None:
        if not response.content:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        record_key = node["config"].get("record_key")
        if record_key and isinstance(payload, dict):
            payload = payload.get(str(record_key))
        return payload if isinstance(payload, dict) else None


def _matches(actual: Any, expected: Any) -> bool:
    if actual is None:
        return False
    if actual == expected:
        return True
    if str(actual) == str(expected):
        return True
    return _same_instant(actual, expected)


def _same_instant(actual: Any, expected: Any) -> bool:
    left, right = _parse_datetime(actual), _parse_datetime(expected)
    return left is not None and right is not None and left == right


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
