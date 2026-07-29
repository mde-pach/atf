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

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from atf.adapters import Context, Record, register
from atf.catalog import Node

HERE = Path(__file__).parent
ROOT = HERE.parent

# Where a command runs when the scenario built no suite for it to run in: an empty directory, made
# once, holding nothing an `atf` walking upwards could mistake for a project.
NOWHERE = Path(tempfile.mkdtemp(prefix="atf-tests-nowhere-"))

# The same marker `atf.compare` uses to say a field is not there, said about a file.
ABSENT = "#absent"

# What a variation writes where the file on disk must hold a literal `${...}`.
KEPT, MEANT = "@{", "${"


class WorkspaceAdapter:
    def __init__(self, settings: dict[str, Any]) -> None:
        # Relative to the manifest, which is this repository's root — the directory above this
        # module. Read relative to the module it used to be resolved against, which was the same
        # place only while the manifest lived in `tests/` too.
        suites = Path(settings.get("suites", "./tests/suites"))
        self.suites = suites if suites.is_absolute() else (ROOT / suites).resolve()
        # The copies made for a *persistent* node, so a second scenario asking for one gets the
        # same suite rather than another copy. Keyed by the whole body, because two nodes over one
        # template with different varied files are two different suites.
        self._kept: dict[str, Path] = {}

    def find(self, node: Node, ctx: Context) -> Record | None:
        """The copy already on disk for this node, where the node is one that is kept.

        An ephemeral workspace is never reused — that is what ephemeral means, and it is what makes a
        scenario running `atf` against a suite safe. A `shared_suite` is the other case: something a
        cockpit is kept alive over, read by pages that only ever GET, and copying it per scenario was
        paying for isolation nothing needed.
        """
        if node["lifecycle"] == "ephemeral":
            return None
        held = self._kept.get(_key(node))
        return {"id": str(held), "suite": str(node["body"]["suite"])} if held and held.is_dir() else None

    def create(self, node: Node, body: Record, ctx: Context) -> Record:
        template = self.suites / str(body["suite"])
        if not template.is_dir():
            raise ValueError(f"{node['id']}: no suite template at {template}")

        root = Path(tempfile.mkdtemp(prefix=f"atf-tests-{body['suite']}-"))
        shutil.copytree(template, root, dirs_exist_ok=True)
        for where, content in body.items():
            if where != "suite":
                _vary(node, root, str(where), content)
        aim_the_command_at(root, ctx)
        if node["lifecycle"] != "ephemeral":
            self._kept[_key(node)] = root
        return {"id": str(root), "suite": str(body["suite"])}

    def delete(self, node: Node, record: Record, ctx: Context) -> None:
        shutil.rmtree(record["id"], ignore_errors=True)

    def close(self) -> None:
        """Take away what was kept for the session. Called once, when the run ends."""
        for root in self._kept.values():
            shutil.rmtree(root, ignore_errors=True)
        self._kept.clear()


def _key(node: Node) -> str:
    """What makes two shared suites the same suite: everything the node says to write."""
    return repr(sorted((str(field), str(value)) for field, value in node["body"].items()))


def aim_the_command_at(root: Path | None, ctx: Any) -> None:
    """Point ATF's `command` system at the suite this scenario built — or at nowhere in particular.

    Every scenario here runs `atf` *inside* the suite it just made, holding that suite's manifest and
    the copy of ATF under test. That is the premise of this whole suite, not something each line
    should have to repeat, so it is settled here and no feature says a word about it. What it buys is
    that every one of them uses ATF's own `When I run "…"` — the surface a reader knows and a user of
    ATF would write — instead of a step of this suite's own.

    Called with no suite, it points at an empty directory with no manifest, which is what a scenario
    running the command *outside* any suite is after.
    """
    command = ctx.adapters.get("command") if hasattr(ctx, "adapters") else None
    if command is None:  # pragma: no cover - the manifest configures one
        return
    command.cwd = str(root or NOWHERE)
    command.env = {
        # Which manifest the command under test reads. Not this repository's — the suite the scenario
        # just built, which is the whole point of building one.
        "ATF_MANIFEST": str(root / "atf.yaml") if root else "",
        # The copy of ATF the command runs, inherited rather than named by a variable of this
        # suite's own. The mutation guard runs the whole suite with `PYTHONPATH` pointing at a
        # deliberately broken tree, and inheriting it is what carries that through to the command —
        # a private `ATF_TESTS_SRC` said the same thing twice.
        "PYTHONPATH": os.pathsep.join(
            filter(None, [os.environ.get("PYTHONPATH", ""), str(root) if root else ""])
        ),
        # `atf` on the path is the one belonging to the interpreter this suite was started with,
        # whatever else the machine has installed. A scenario that runs a different ATF is not
        # testing this one.
        "PATH": os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")]),
    }


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
