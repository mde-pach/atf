"""ATF's own test suite — an ATF suite, plus the Python tests that could not be one.

This repository *is* a consuming project. `atf.yaml` is at the root, where a project's config
belongs and where ATF finds it by walking up, so `atf status local`, `atf run`, `atf lint` and
`atf serve` all work with nothing exported first. `pytest` from the root runs the scenarios through
the same plugin any other suite uses. If that is awkward, the framework is awkward.

**Nothing is set up here any more, and that is the point.** This file used to start an HTTP server
as an import side effect and write three variables into the environment, so that `*_env` pointers in
the manifest would resolve by the time the plugin imported. The manifest writes its address down
instead; the environment is [started like a dev server](backend.py), by the session fixture in
`specs/conftest.py` or by you in another terminal. What is left here is the fixtures the Python tests
share, and one line of registration.

`suites/` is excluded from collection. Those are complete suites-under-test, copied into a temp
directory per scenario; collecting them here would run them in this process, against this manifest.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

pytest_plugins = ["atf.spec.plugin", "pytester"]

# Complete suites on disk, for the `workspace` adapter to copy. Not this suite's tests.
collect_ignore_glob = ["suites/*"]

from atf.adapters import unregister  # noqa: E402 - after this directory is on the path
from atf.engine.materializer import Materializer  # noqa: E402
from tests.fake_adapter import register_fake  # noqa: E402
from tests.sample_project import write_sample_project  # noqa: E402


@pytest.fixture
def project(tmp_path: Path):
    """A complete consuming project on disk, run in its own process by `run_pytest`."""
    return write_sample_project(tmp_path / "suite")


@pytest.fixture
def fake():
    adapter = register_fake("fake")
    yield adapter
    unregister("fake")


@pytest.fixture
def write_catalog(tmp_path: Path):
    def _write(files: dict[str, str]) -> Path:
        root = tmp_path / "catalog"
        root.mkdir(exist_ok=True)
        for name, text in files.items():
            (root / name).write_text(text, encoding="utf-8")
        return root

    return _write


GOOD_TYPES = """
account:
  system: fake
  natural_key: email
project:
  system: fake
  natural_key: [account_id, slug]
job_run:
  system: fake
  natural_key: token
  id_field: uuid
lead:
  system: fake
  lifecycle: ephemeral
  natural_key: email
widget:
  system: fake
  mode: reference
  natural_key: name
  ref_field: name
sighting:
  system: fake
  mode: data
  natural_key: name
  ref_field: name
"""

GOOD_INSTANCES = {
    "accounts.yaml": """
primary:
  resource: account
  represents: The main account.
  body:
    email: primary@example.test
""",
    "projects.yaml": """
alpha:
  resource: project
  represents: A project under the primary account.
  depends_on:
    - accounts.primary
  body:
    slug: alpha
    account_id: ${accounts.primary.id}
""",
    "runs.yaml": """
nightly:
  resource: job_run
  represents: A nightly run.
  depends_on:
    - projects.alpha
  body:
    token: nightly
    project_id: ${projects.alpha.id}
""",
    "leads.yaml": """
walkin:
  resource: lead
  represents: An ephemeral lead.
  body:
    email: walkin@example.test
""",
    "widgets.yaml": """
imported:
  resource: widget
  represents: A widget that must already exist.
  body:
    name: imported
""",
    "sightings.yaml": """
watched:
  resource: sighting
  represents: Something to look at — it may or may not be there, and either is an answer.
  body:
    name: watched
""",
}


@pytest.fixture
def good_catalog(write_catalog):
    return write_catalog({"resources.yaml": GOOD_TYPES, **GOOD_INSTANCES})


@pytest.fixture
def engine(good_catalog, fake):
    return Materializer(good_catalog, "test", {"fake": fake})
