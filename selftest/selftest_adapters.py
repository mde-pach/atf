"""The workspace adapter: provisioning a resource here means putting a real suite on disk.

`create` copies a suite template into a temp directory; the identity is its path, so specs can
run `atf` inside it. `delete` removes it — which is how the ephemeral lifecycle is exercised
against the framework's own teardown path.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from atf.adapters import Context, Record, register
from atf.catalog import Node

HERE = Path(__file__).parent


class WorkspaceAdapter:
    def __init__(self, settings: dict[str, Any]) -> None:
        suites = Path(settings.get("suites", "./suites"))
        self.suites = suites if suites.is_absolute() else (HERE / suites).resolve()

    def find(self, node: Node, ctx: Context) -> Record | None:
        return None  # ephemeral: never reused between scenarios

    def create(self, node: Node, body: Record, ctx: Context) -> Record:
        template = self.suites / str(body["suite"])
        if not template.is_dir():
            raise ValueError(f"{node['id']}: no suite template at {template}")

        root = Path(tempfile.mkdtemp(prefix=f"atf-selftest-{body['suite']}-"))
        shutil.copytree(template, root, dirs_exist_ok=True)
        return {"id": str(root), "suite": str(body["suite"])}

    def delete(self, node: Node, record: Record, ctx: Context) -> None:
        shutil.rmtree(record["id"], ignore_errors=True)


register("workspace", WorkspaceAdapter)
