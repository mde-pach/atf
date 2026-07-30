"""Guards for the properties the framework promises, independent of any one project.

Six tests used to live here that read ATF's own source and matched it with a regular expression:
no product URL, no hardcoded credential, no `type: ignore`, no backend named in the materializer,
every entry point through `bootstrap`, the cockpit's default host. They are gone, and it is worth
saying why rather than leaving the gap to be refilled.

They were **lint rules wearing test costumes**. A convention that can only be broken by a person
editing the repository is not a behaviour that can regress; it belongs to review or to a linter. As
tests they were trivially defeatable, they broke on refactors that changed nothing, and a failure
read as *"the software is broken"* when it meant *"somebody wrote something we agreed not to"*.
The credential and `type: ignore` rules moved to ruff, where they are enforced properly and named
in `pyproject.toml`. The rest are review's job.

There is an irony in having shipped them at all: this session deleted `atf lint`'s content rules on
the grounds that inferring meaning from syntax cannot work, while this file did exactly that to
ATF's own source.

**Two assertions about artefacts stay**, and they are deliberate exceptions rather than an oversight:
the vendored htmx is checked for a pinned version and a hash, because it is a third-party file
shipped to users and no linter reads it; and `agent/mcp.py` is checked to import nothing from the modules
that hold the vocabulary, because it is the guard that makes the coverage test above it impossible to
defeat by moving a list. Both are named here so a reader knows the difference.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "atf"






def test_adapters_are_registered_as_factories_not_instances():
    from atf.adapters import build, registered_systems

    assert {"rest", "reference"} <= registered_systems()
    first = build("rest", {"base_url": "http://127.0.0.1:1"})
    second = build("rest", {"base_url": "http://127.0.0.1:2"})
    assert first is not second
    assert first.base_url != second.base_url  # each gets its own environment's settings




def test_serving_a_public_host_prints_a_warning(monkeypatch, capsys, tmp_path):
    import atf.cli as cli

    started: dict[str, object] = {}

    class FakeUvicorn:
        @staticmethod
        def run(app, host, port, log_level):
            started.update(host=host, port=port)

    monkeypatch.setitem(__import__("sys").modules, "uvicorn", FakeUvicorn)

    manifest = tmp_path / "atf.yaml"
    manifest.write_text(
        "catalog: ./catalog\nspecs: ./specs\ndefault_env: dev\nmutable_envs: [dev]\nenvironments:\n  dev: {}\n",
        encoding="utf-8",
    )
    (tmp_path / "catalog").mkdir()
    (tmp_path / "catalog" / "resources.yaml").write_text("", encoding="utf-8")
    monkeypatch.setenv("ATF_MANIFEST", str(manifest))

    monkeypatch.setattr("atf.cockpit.app.create_app", lambda env=None, mcp_host=None: object())
    assert cli.main(["serve", "--host", "0.0.0.0"]) == 0

    captured = capsys.readouterr()
    assert "NO authentication" in captured.out
    assert "WARNING" in captured.err and "0.0.0.0" in captured.err
    assert started["host"] == "0.0.0.0"


def test_serving_localhost_prints_the_banner_without_a_warning(monkeypatch, capsys, tmp_path):
    import atf.cli as cli

    class FakeUvicorn:
        @staticmethod
        def run(app, host, port, log_level):
            return None

    monkeypatch.setitem(__import__("sys").modules, "uvicorn", FakeUvicorn)
    manifest = tmp_path / "atf.yaml"
    manifest.write_text(
        "catalog: ./catalog\nspecs: ./specs\ndefault_env: dev\nmutable_envs: [dev]\nenvironments:\n  dev: {}\n",
        encoding="utf-8",
    )
    (tmp_path / "catalog").mkdir()
    (tmp_path / "catalog" / "resources.yaml").write_text("", encoding="utf-8")
    monkeypatch.setenv("ATF_MANIFEST", str(manifest))
    monkeypatch.setattr("atf.cockpit.app.create_app", lambda env=None, mcp_host=None: object())

    assert cli.main(["serve"]) == 0
    captured = capsys.readouterr()
    assert "127.0.0.1" in captured.out
    assert "Mutable environments: dev" in captured.out
    assert captured.err == ""


def test_the_introspection_api_reaches_every_word_the_framework_knows(tmp_path, monkeypatch):
    """The whole condition the MCP surface was accepted under: it must not need maintaining.

    An agent composing through MCP can only say what `describe` offers it. So the moment ATF learns
    a word that `describe` does not surface, the surface has silently become a subset of the
    framework — and the failure is invisible, because everything that *is* offered still works.

    This is the guard against that. It stands up a real suite, discovers it the way the cockpit
    does, and requires the three tables that define ATF's vocabulary to come back out whole:

    - every `GENERIC_STEPS` wording is offered, and recognised as ATF's own rather than mistaken
      for something the project wrote;
    - every `COMPARISONS` entry is offered, *and* the step it writes is one of those wordings — a
      claim the composer can express but pytest cannot run is worse than one it cannot express;
    - every `MARKERS` entry is offered with what it means.

    Each of the three fails for a different kind of drift, which is why all three are here. A new
    generic step reaches the surface through discovery, so what would drop it is a *filter* — and
    that is what the first check catches; it has already caught a wording declared in the table and
    never registered. Comparisons and markers reach it by being read out of their tables, so the way
    to break those is for the surface to grow a *copy* of the list — and comparing the answer with
    the tables themselves is what makes a copy fail the moment it falls behind. Nothing here writes
    out an expected word, so nothing here can be satisfied by updating a second copy.
    """
    import sys

    from atf.agent.introspect import FROM_ATF, Surface, describe
    from atf.engine.bootstrap import bootstrap
    from atf.model.compare import MARKERS
    from atf.spec.vocabulary import COMPARISONS, GENERIC_STEPS
    from atf.suite.discovery import discover
    from tests.sample_project import write_sample_project

    root = write_sample_project(tmp_path / "suite")
    monkeypatch.setenv("ATF_MANIFEST", str(root / "atf.yaml"))
    monkeypatch.setenv("ATF_ENV", "dev")
    monkeypatch.setenv("PYTHONPATH", str(SRC.parent.parent))
    monkeypatch.chdir(root)
    monkeypatch.delitem(sys.modules, "suite_adapters", raising=False)

    boot = bootstrap("dev")
    engine = boot.materializer
    found = discover(boot.manifest.specs_dir, engine.catalog, "dev", boot.manifest.root)
    assert found.errors == [], found.errors

    described = describe(
        Surface(
            env="dev",
            root=boot.manifest.root,
            specs_dir=boot.manifest.specs_dir,
            engine=engine,
            found=found,
        )
    )

    offered = {one["pattern"]: one for group in described["steps"].values() for one in group}
    missing = [one.pattern for one in GENERIC_STEPS if one.pattern not in offered]
    assert missing == [], f"the introspection API offers no way to say: {missing}"
    mistaken = [one.pattern for one in GENERIC_STEPS if offered[one.pattern]["defined_by"] != FROM_ATF]
    assert mistaken == [], f"offered, but not as ATF's own: {mistaken}"

    assert {one.key for one in COMPARISONS} == {one["key"] for one in described["comparisons"]}
    unrunnable = [one.key for one in COMPARISONS if one.pattern not in offered]
    assert unrunnable == [], f"a claim that composes into a step nothing offers: {unrunnable}"

    assert {one["marker"]: one["means"] for one in described["markers"]} == MARKERS


def test_the_mcp_layer_cannot_hold_a_copy_of_the_vocabulary():
    """Why the guard above can never be defeated by editing the MCP layer instead.

    `agent/mcp.py` does not import the tables that define ATF's words, so it has no way to enumerate them
    and no way to hold a stale copy of one. Everything it can say about the vocabulary it has to ask
    `agent/introspect.py` for. That is what makes three tools enough forever: a tool per step would have
    needed editing every time the framework learnt a word, and this cannot.
    """
    tree = ast.parse((SRC / "agent/mcp.py").read_text(encoding="utf-8"))
    reached = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not reached & {"steps", "compare", "discovery", "catalog"}, (
        f"agent/mcp.py reaches for the vocabulary directly: {sorted(reached)}"
    )


def test_htmx_is_vendored_with_a_pinned_version_and_no_cdn_reference():
    static = SRC / "cockpit" / "static" / "htmx.min.js"
    header = static.read_text(encoding="utf-8")[:400]
    assert re.search(r"htmx \d+\.\d+\.\d+", header)
    assert "sha384-" in header

    for template in (SRC / "cockpit" / "templates").rglob("*.html"):
        body = template.read_text(encoding="utf-8")
        assert "unpkg" not in body and "cdn" not in body.lower()


# The layers, innermost first. A module may import from its own layer and from any layer before it.
LAYERS = ("model", "adapters", "engine", "spec", "run", "suite", "agent", "cockpit")


def test_every_import_points_downward():
    """The direction is the design: what a layer may know about is what is under it.

    `cli.py` and `session.py` sit outside the layers on purpose — composing them is what they are
    for — so they are the two modules this does not constrain.
    """
    import ast

    rank = {name: index for index, name in enumerate(LAYERS)}
    upward: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        parts = path.relative_to(SRC).parts
        if len(parts) == 1:
            continue
        here = parts[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ImportFrom) or not node.level:
                continue
            base = list(parts[:-1])
            up = node.level - 1
            named = (base[: len(base) - up] if up else base) + (node.module or "").split(".")
            there = named[0] if named and named[0] in rank else None
            if there and there != here and rank[there] > rank[here]:
                upward.append(f"{'/'.join(parts)} imports {there}.{node.module}")
    assert upward == [], "these imports point outward, which makes the layering a suggestion"


@pytest.mark.parametrize(
    "name",
    [
        "model/manifest.py",
        "model/catalog.py",
        "model/placeholders.py",
        "engine/materializer.py",
        "adapters/__init__.py",
    ],
)
def test_core_modules_are_import_safe(name):
    """Importing the engine must never open a socket."""
    import subprocess
    import sys

    module = "atf." + name.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
    # A fresh interpreter: importing in-process is a no-op once conftest has imported these.
    guard = (
        "import ssl, socket\n"  # let the stdlib finish importing before swapping anything
        "_real = socket.socket\n"
        "class Guard(_real):\n"
        "    def connect(self, *a, **k): raise AssertionError('connected at import time')\n"
        "    def connect_ex(self, *a, **k): raise AssertionError('connected at import time')\n"
        "socket.socket = Guard\n"
        "def _boom(*a, **k): raise AssertionError('connected at import time')\n"
        "socket.create_connection = _boom\n"
        f"import {module}\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", guard],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONPATH": str(SRC.parent)},
    )
    assert completed.returncode == 0, f"{name} is not import-safe:\n{completed.stderr}"


def test_loading_a_catalog_touches_nothing_but_the_filesystem(good_catalog, monkeypatch):
    """Importing `model/catalog.py` is guarded above; *calling* its loader is guarded here.

    The loader's promise is that a catalog can be read, and every problem in it reported, in a
    checkout with no environment anywhere near it — which is what lets `atf lint` and the cockpit's
    catalog page work offline, and what stops a validation error being a connection error wearing
    a disguise. It moved here from `tests/test_catalog.py` when that module became scenarios: a
    rule about what the framework may not do has no observable surface to write a scenario against.
    """
    import socket

    from atf.model.catalog import load_catalog

    def explode(*args, **kwargs):
        raise AssertionError("catalog loader must not touch the network")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr(socket, "create_connection", explode)

    # The assertion is `explode`: the loader reaching for the network fails the test from inside it.
    # Said out loud because a test body that just calls something and ends reads like an oversight,
    # and what it is worth checking is also that the loader still did its job.
    catalog = load_catalog(good_catalog, {"fake"})
    assert catalog.types and catalog.nodes, "the loader read nothing, so it proved nothing about not connecting"
