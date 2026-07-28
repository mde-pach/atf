"""The stub backend the suites under test provision into, as this suite talks to it.

Running the command under test is ATF's own `command` adapter now — argv, the environment, the
working directory, the exit code, both streams and what `ok` means all live there, because they are
the shape of a class of system rather than anything about ATF. What is left is this: an HTTP client
for reading and resetting the stand-in API, which is genuinely this suite's own business.
"""

from __future__ import annotations

from typing import Any

import httpx


class Backend:
    def __init__(self, backend_url: str, actor: str) -> None:
        self.backend_url = backend_url
        self.actor = actor
        self.http = httpx.Client(base_url=backend_url, headers={"X-Actor": actor}, timeout=10)

    def records(self, collection: str) -> list[dict[str, Any]]:
        response = self.http.get(f"/{collection}")
        response.raise_for_status()
        return response.json()["results"]

    def reset(self) -> None:
        httpx.post(f"{self.backend_url}/_reset", timeout=10).raise_for_status()
