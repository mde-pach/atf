"""The workspace adapter: provisioning a resource here means putting a real suite on disk.

`create` copies a suite template into a temp directory; the identity is its path, so specs can
run `atf` inside it. `delete` removes it — which is how the ephemeral lifecycle is exercised
against the framework's own teardown path.

**A variation is a file written over the copy.** Most of what this suite has to say about ATF is
"here is a manifest with one thing wrong with it, and here is what the command says about it".
A template per malformation would be forty directories that differ by three lines each — a global
set of named fixtures where every variation needs a new one, which is the Object Mother pattern
`Given … but:` exists to replace. So a body key that is not `suite` names a path inside the copied
workspace, and the cell holds that file's text:

```gherkin
Given the workspace "bare" but:
  | catalog/resources.yaml | {account: {system: quantum}} |
When I run "atf status local"
Then it is refused because "no registered adapter"
```

Flow-style YAML fits on one line because a broken catalog is small by nature: it exists to have one
thing wrong with it. Two conventions carry the rest — `#absent` removes a file or directory, and
`@{...}` is written where the file must *contain* an unresolved `${...}`, since the materializer
resolves a body before an adapter ever sees it and a catalog whose whole point is a placeholder
typo would otherwise fail out here instead of in there.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from atf.adapters import Context, Record, register
from atf.catalog import Node

HERE = Path(__file__).parent

# The same marker `atf.compare` uses to say a field is not there, said about a file.
ABSENT = "#absent"

# What a variation writes where the file on disk must hold a literal `${...}`.
KEPT, MEANT = "@{", "${"


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

        root = Path(tempfile.mkdtemp(prefix=f"atf-tests-{body['suite']}-"))
        shutil.copytree(template, root, dirs_exist_ok=True)
        for where, content in body.items():
            if where != "suite":
                _vary(node, root, str(where), content)
        return {"id": str(root), "suite": str(body["suite"])}

    def delete(self, node: Node, record: Record, ctx: Context) -> None:
        shutil.rmtree(record["id"], ignore_errors=True)


def _vary(node: Node, root: Path, where: str, content: Any) -> None:
    """Write one varied file into the copy, or take one away."""
    # Both resolved: a temp directory is reached through a symlink on macOS, so comparing an
    # unresolved root against a resolved target would call every path an escape.
    root = root.resolve()
    target = (root / where).resolve()
    if root not in target.parents:
        raise ValueError(f"{node['id']}: {where!r} points outside the workspace")

    if str(content).strip() == ABSENT:
        shutil.rmtree(target, ignore_errors=True)
        target.unlink(missing_ok=True)
        return

    text = "" if content is None else str(content).replace(KEPT, MEANT)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


register("workspace", WorkspaceAdapter)
