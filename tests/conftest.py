"""ATF's own test suite — an ATF suite, plus the Python tests that could not be one.

`tests/` *is* a consuming project: `atf.yaml`, a catalog, `specs/`, and suite templates under
`suites/`. Running `pytest` from the repository root runs ATF's scenarios against a stub backend
and a real cockpit, through the same plugin any other suite uses. If that is awkward, the framework
is awkward.

This file does two jobs. It starts the stub environment *before* `atf.plugin` bootstraps — the
plugin builds its adapters at import, so the backend has to be answering by then — and it holds the
fixtures the remaining Python tests share.

`suites/` is excluded from collection. Those are complete suites-under-test, copied into a temp
directory per scenario; collecting them here would run them in this process, against this manifest.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

# Where the suites under test provision into. Started here rather than in a fixture because the
# plugin resolves `${env:...}` settings when it imports, which is before any fixture runs.
if not os.environ.get("ATF_TESTS_BACKEND"):
    from stub_backend import StubBackend

    os.environ.setdefault("ATF_TESTS_ACTOR", "atf-tests")
    _backend = StubBackend(actor=os.environ["ATF_TESTS_ACTOR"])
    os.environ["ATF_TESTS_BACKEND"] = _backend.start()

# Which manifest this suite is. Set here because pytest runs from the repository root, and ATF
# would otherwise walk up from there and find no suite at all.
os.environ.setdefault("ATF_MANIFEST", str(HERE / "atf.yaml"))

# Which copy of ATF the command under test runs. The mutation guard overrides it to aim a scenario
# at a deliberately broken one; left alone it is the working tree.
os.environ.setdefault("ATF_TESTS_SRC", str(HERE.parent / "src"))

pytest_plugins = ["atf.plugin", "pytester"]

# Complete suites on disk, for the `workspace` adapter to copy. Not this suite's tests.
collect_ignore_glob = ["suites/*"]

from atf.adapters import unregister  # noqa: E402 - after the environment above is in place
from atf.materializer import Materializer  # noqa: E402
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
