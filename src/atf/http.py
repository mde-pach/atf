"""Shared HTTP plumbing: auth schemes, retries and paginated listings.

Adapters and system-under-test clients apply auth the same way, so both live here.
"""

from __future__ import annotations

import time
from collections.abc import Generator, Iterable, Mapping
from typing import Any

import httpx
from typing_extensions import override

DEFAULT_TIMEOUT = 30.0
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 1000
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS"})
_TOKEN_KEYS = ("token", "access_token", "session_token", "key", "jwt")


class AuthError(Exception):
    pass


def build_client(
    base_url: str,
    auth: Mapping[str, Any] | str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    headers: Mapping[str, str] | None = None,
    verify: bool = True,
) -> httpx.Client:
    """An `httpx.Client` with the manifest's auth scheme applied (values already env-resolved)."""
    scheme_headers, flow = _auth_parts(auth)
    merged = {**scheme_headers, **dict(headers or {})}
    return httpx.Client(
        base_url=base_url.rstrip("/"),
        timeout=timeout,
        headers=merged,
        auth=flow,
        verify=verify,
        follow_redirects=True,
    )


def _auth_parts(auth: Mapping[str, Any] | str | None) -> tuple[dict[str, str], httpx.Auth | None]:
    if auth is None or auth == "none" or auth == {}:
        return {}, None
    if isinstance(auth, str):
        raise AuthError(f"unknown auth scheme {auth!r}")

    if "none" in auth:
        return {}, None
    if "header" in auth:
        name = str(auth["header"])
        value = auth.get("value")
        if value is None:
            raise AuthError("header auth needs `value_env` (or `value`)")
        return {name: str(value)}, None
    if "bearer" in auth:
        spec = auth["bearer"]
        token = spec.get("token") if isinstance(spec, Mapping) else spec
        if not token:
            raise AuthError("bearer auth needs `token_env` (or `token`)")
        return {"Authorization": f"Bearer {token}"}, None
    if "session" in auth:
        spec = auth["session"]
        if not isinstance(spec, Mapping):
            raise AuthError("session auth needs a mapping with `login_path`")
        return {}, SessionAuth(spec)

    raise AuthError(f"unknown auth scheme {sorted(auth)}; expected none/header/bearer/session")


class SessionAuth(httpx.Auth):
    """Logs in once (lazily, on the first request) and reuses the session cookie/token."""

    requires_response_body = True

    def __init__(self, spec: Mapping[str, Any]) -> None:
        self.login_path = str(spec.get("login_path") or "/login")
        self.username = spec.get("username")
        self.password = spec.get("password")
        self.username_field = str(spec.get("username_field") or "username")
        self.password_field = str(spec.get("password_field") or "password")
        self.token_key = spec.get("token_key")
        self.token_header = str(spec.get("token_header") or "Authorization")
        self.token_format = str(spec.get("token_format") or "Bearer {token}")
        self.form = bool(spec.get("form", False))
        self._headers: dict[str, str] = {}
        self._ready = False

    @override
    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        # httpx reads the response body for us because `requires_response_body` is set.
        if not self._ready:
            response = yield self._login_request(request)
            self._capture(response)
            self._ready = True
        for name, value in self._headers.items():
            request.headers[name] = value
        yield request

    def _login_request(self, request: httpx.Request) -> httpx.Request:
        url = request.url.join(self.login_path)
        payload = {self.username_field: self.username, self.password_field: self.password}
        if self.form:
            return httpx.Request("POST", url, data=payload)
        return httpx.Request("POST", url, json=payload)

    def _capture(self, response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise AuthError(f"session login failed: {response.status_code} {response.text[:200]}")

        cookies = httpx.Cookies()
        cookies.extract_cookies(response)
        jar = {name: value for name, value in cookies.items()}
        if jar:
            self._headers["Cookie"] = "; ".join(f"{name}={value}" for name, value in jar.items())

        token = self._token_from(response)
        if token:
            self._headers[self.token_header] = self.token_format.format(token=token)
        if not self._headers:
            raise AuthError("session login returned neither a cookie nor a token")

    def _token_from(self, response: httpx.Response) -> str | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None
        if self.token_key:
            value = payload.get(str(self.token_key))
            return None if value is None else str(value)
        for key in _TOKEN_KEYS:
            if key in payload and payload[key]:
                return str(payload[key])
        return None


def request(
    client: httpx.Client,
    method: str,
    url: str,
    retries: int = 0,
    backoff: float = 0.2,
    **kwargs: Any,
) -> httpx.Response:
    """One request, retrying transport errors and 5xx with exponential backoff.

    Only idempotent methods are retried: a backend that creates the record and *then* fails
    would otherwise be sent a duplicate, which is exactly what get-or-create must never do.
    """
    if method.upper() not in IDEMPOTENT_METHODS:
        retries = 0
    attempt = 0
    while True:
        try:
            response = client.request(method, url, **kwargs)
        except httpx.TransportError:
            if attempt >= retries:
                raise
        else:
            if response.status_code < 500 or attempt >= retries:
                return response
        time.sleep(backoff * (2**attempt))
        attempt += 1


def list_records(
    client: httpx.Client,
    url: str,
    params: Mapping[str, Any] | None = None,
    pagination: Mapping[str, Any] | None = None,
    retries: int = 0,
) -> list[dict[str, Any]]:
    """A whole collection: a bare list response, or offset paging via `results_key`/`count_key`."""
    query: dict[str, Any] = dict(params or {})
    if not pagination:
        return _records_from(_json(request(client, "GET", url, retries=retries, params=query), url))

    results_key = str(pagination.get("results_key", "results"))
    count_key = str(pagination.get("count_key", "count"))
    limit_param = str(pagination.get("limit_param", "limit"))
    offset_param = str(pagination.get("offset_param", "offset"))
    page_size = int(pagination.get("page_size", DEFAULT_PAGE_SIZE))

    max_pages = int(pagination.get("max_pages", DEFAULT_MAX_PAGES))
    collected: list[dict[str, Any]] = []
    offset = 0
    for _ in range(max_pages):
        page_query = {**query, limit_param: page_size, offset_param: offset}
        payload = _json(request(client, "GET", url, retries=retries, params=page_query), url)
        if isinstance(payload, list):
            return _records_from(payload)
        page = payload.get(results_key)
        if not isinstance(page, list):
            raise ValueError(f"{url}: response has no {results_key!r} list")
        collected.extend(item for item in page if isinstance(item, dict))
        total = payload.get(count_key)
        offset += len(page)

        # A backend that ignores `limit`/`offset` returns page 1 forever, and one with no
        # `count_key` never satisfies the total check — so a short page also ends it.
        if not page or len(page) < page_size or (isinstance(total, int) and offset >= total):
            return collected

    raise ValueError(
        f"{url}: still paginating after {max_pages} pages ({len(collected)} records) — "
        "the backend may be ignoring the offset parameter"
    )


def _json(response: httpx.Response, url: str) -> Any:
    if response.status_code >= 400:
        raise ValueError(f"{url}: {response.status_code} {response.text[:200]}")
    try:
        return response.json()
    except ValueError as exc:
        raise ValueError(f"{url}: response was not JSON: {exc}") from exc


def _records_from(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise ValueError(f"expected a list response, got {type(payload).__name__}")


def as_query(values: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    return {name: value for name, value in values if value is not None}
