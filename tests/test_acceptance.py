"""Guards for the properties the framework promises, independent of any one project."""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "atf"
# `atf init` writes starter files for the *user's* project; RFC-2606 placeholders belong there.
SCAFFOLD = SRC / "scaffold.py"

DOMAINISH = re.compile(r"https?://(?!127\.0\.0\.1|localhost|\{)[^\s\"'<>)]+")


def python_sources() -> list[Path]:
    return sorted(path for path in SRC.rglob("*.py") if path != SCAFFOLD)


def test_the_framework_names_no_product_domain_or_url():
    offenders: list[str] = []
    for path in [*python_sources(), *SRC.rglob("*.html")]:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in DOMAINISH.findall(line):
                offenders.append(f"{path.relative_to(SRC)}:{number}: {match}")
    assert offenders == []


def test_the_framework_carries_no_secrets():
    """Secrets only ever arrive through `*_env` pointers resolved at bootstrap."""
    suspicious = re.compile(r"""(password|secret|token|api_key)\s*=\s*["'][^"']{6,}["']""", re.IGNORECASE)
    offenders = [
        f"{path.relative_to(SRC)}:{number}"
        for path in python_sources()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if suspicious.search(line)
    ]
    assert offenders == []


def test_the_materializer_has_no_per_system_branching():
    """The engine dispatches through the registry; it must never name a backend."""
    source = (SRC / "materializer.py").read_text(encoding="utf-8")
    for system in ("rest", "http", "sql", "graphql", "grpc"):
        assert f'"{system}"' not in source and f"'{system}'" not in source


def test_no_type_ignore_suppressions_in_the_framework():
    """`scaffold.py` is excluded: its strings are files written into the *user's* project."""
    offenders = [
        f"{path.relative_to(SRC)}:{number}"
        for path in python_sources()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if "type: ignore" in line or "noqa: F" in line
    ]
    assert offenders == []


def test_adapters_are_registered_as_factories_not_instances():
    from atf.adapters import build, registered_systems

    assert {"rest", "reference"} <= registered_systems()
    first = build("rest", {"base_url": "http://127.0.0.1:1"})
    second = build("rest", {"base_url": "http://127.0.0.1:2"})
    assert first is not second
    assert first.base_url != second.base_url  # each gets its own environment's settings


def test_every_entry_point_configures_itself_through_bootstrap():
    """plugin, cockpit deps and CLI must all funnel through `bootstrap`."""
    for module in ("plugin.py", "cockpit/deps.py", "cli.py"):
        source = (SRC / module).read_text(encoding="utf-8")
        assert "bootstrap" in source, module
        assert "load_catalog(" not in source, f"{module} must not load the catalog itself"


def test_the_cockpit_binds_localhost_by_default():
    tree = ast.parse((SRC / "cli.py").read_text(encoding="utf-8"))
    defaults = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == "127.0.0.1"
    ]
    assert defaults, "`atf serve --host` must default to 127.0.0.1"


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

    from atf.bootstrap import bootstrap
    from atf.compare import MARKERS
    from atf.discovery import discover
    from atf.introspect import FROM_ATF, Surface, describe
    from atf.steps import COMPARISONS, GENERIC_STEPS
    from tests.sample_project import write_sample_project

    root = write_sample_project(tmp_path / "suite")
    monkeypatch.setenv("ATF_MANIFEST", str(root / "atf.yaml"))
    monkeypatch.setenv("ATF_ENV", "dev")
    monkeypatch.setenv("PYTHONPATH", str(SRC.parent.parent))
    monkeypatch.chdir(root)
    monkeypatch.delitem(sys.modules, "suite_adapters", raising=False)

    boot = bootstrap("dev")
    engine = boot.materializer
    found = discover(
        boot.manifest.specs_dir, engine.nodes, set(engine.types), "dev", boot.manifest.root
    )
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

    `mcp.py` does not import the tables that define ATF's words, so it has no way to enumerate them
    and no way to hold a stale copy of one. Everything it can say about the vocabulary it has to ask
    `introspect.py` for. That is what makes three tools enough forever: a tool per step would have
    needed editing every time the framework learnt a word, and this cannot.
    """
    tree = ast.parse((SRC / "mcp.py").read_text(encoding="utf-8"))
    reached = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not reached & {"steps", "compare", "discovery", "catalog"}, (
        f"mcp.py reaches for the vocabulary directly: {sorted(reached)}"
    )


def test_htmx_is_vendored_with_a_pinned_version_and_no_cdn_reference():
    static = SRC / "cockpit" / "static" / "htmx.min.js"
    header = static.read_text(encoding="utf-8")[:400]
    assert re.search(r"htmx \d+\.\d+\.\d+", header)
    assert "sha384-" in header

    for template in (SRC / "cockpit" / "templates").rglob("*.html"):
        body = template.read_text(encoding="utf-8")
        assert "unpkg" not in body and "cdn" not in body.lower()


@pytest.mark.parametrize(
    "name",
    ["config.py", "catalog.py", "materializer.py", "placeholders.py", "adapters/__init__.py"],
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
    """Importing `catalog.py` is guarded above; *calling* its loader is guarded here.

    The loader's promise is that a catalog can be read, and every problem in it reported, in a
    checkout with no environment anywhere near it — which is what lets `atf lint` and the cockpit's
    catalog page work offline, and what stops a validation error being a connection error wearing
    a disguise. It moved here from `tests/test_catalog.py` when that module became scenarios: a
    rule about what the framework may not do has no observable surface to write a scenario against.
    """
    import socket

    from atf.catalog import load_catalog

    def explode(*args, **kwargs):
        raise AssertionError("catalog loader must not touch the network")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr(socket, "create_connection", explode)
    load_catalog(good_catalog, {"fake"})
