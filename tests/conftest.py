from __future__ import annotations

from pathlib import Path

import pytest

from atf.adapters import unregister
from atf.materializer import Materializer
from tests.fake_adapter import register_fake
from tests.sample_project import write_sample_project

pytest_plugins = ["pytester"]


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
}


@pytest.fixture
def good_catalog(write_catalog):
    return write_catalog({"resources.yaml": GOOD_TYPES, **GOOD_INSTANCES})


@pytest.fixture
def materializer(good_catalog, fake):
    return Materializer(good_catalog, "test", {"fake": fake})
