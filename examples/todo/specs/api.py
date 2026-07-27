"""The system under test, as the specs see it.

Its base URL and auth come from `environments.<env>.clients.api` — deliberately separate from
the provisioning adapters, because the consumer surface may differ from the admin one.

One method per action a `When` performs, and nothing else. Reading a resource back to assert on
it used to live here too; ATF's own steps do that now, through the adapter the catalog already
declares, so the client only carries what the suite actually *does*.
"""

from __future__ import annotations

from typing import Any

import pytest

from atf import http


class TodoApi:
    def __init__(self, base_url: str, auth: dict[str, Any] | None = None) -> None:
        self.http = http.build_client(base_url, auth=auth, timeout=10)

    def lists_of(self, owner: dict[str, Any]) -> list[dict[str, Any]]:
        return self._results("/lists", {"owner_id": owner["id"]})

    def tasks_in(self, todo_list: dict[str, Any]) -> list[dict[str, Any]]:
        return self._results("/tasks", {"list_id": todo_list["id"]})

    def complete(self, task: dict[str, Any]) -> dict[str, Any]:
        response = self.http.patch(f"/tasks/{task['uuid']}", json={"done": True})
        response.raise_for_status()
        return response.json()

    def _results(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        response = self.http.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        return payload["results"] if isinstance(payload, dict) else payload


@pytest.fixture
def api(client_config):
    return TodoApi(**client_config["api"])
