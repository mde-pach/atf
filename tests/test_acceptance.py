"""Guards for the acceptance criteria that are properties of the framework itself (§20)."""

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
    """plugin, cockpit deps and CLI must all funnel through `bootstrap` (§4.3)."""
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

    monkeypatch.setattr("atf.cockpit.app.create_app", lambda env=None: object())
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
    monkeypatch.setattr("atf.cockpit.app.create_app", lambda env=None: object())

    assert cli.main(["serve"]) == 0
    captured = capsys.readouterr()
    assert "127.0.0.1" in captured.out
    assert "Mutable environments: dev" in captured.out
    assert captured.err == ""


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
