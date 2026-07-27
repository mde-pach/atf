"""The pytest plugin: context, generated resource factories, one generic step, teardown.

Enable it from a consuming project's `conftest.py`:

    pytest_plugins = ["atf.plugin"]
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from pytest_bdd import given, parsers

from .adapters import Record
from .bootstrap import Boot, bootstrap
from .materializer import Materializer
from .runner import PROGRESS_OUT

_BOOT: Boot = bootstrap()

EPHEMERAL_ATTR = "_ephemeral"


@pytest.fixture(scope="session")
def materializer() -> Materializer:
    """The provisioning engine for the active environment."""
    return _BOOT.materializer


@pytest.fixture(scope="session")
def env() -> str:
    """The active environment name (`ATF_ENV`, else the manifest's `default_env`)."""
    return _BOOT.env


@pytest.fixture
def client_config(env: str) -> dict[str, dict[str, Any]]:
    """Resolved settings for the system-under-test client(s), from `environments.<env>.clients`."""
    return _BOOT.clients


@pytest.fixture
def context() -> SimpleNamespace:
    """The per-scenario scratchpad: steps write what they create and read what they need."""
    return SimpleNamespace()


def _make_factory(resource_type: str) -> Any:
    def _factory(
        request: pytest.FixtureRequest, materializer: Materializer, context: SimpleNamespace
    ) -> Callable[[str], Record]:
        def provision(name: str) -> Record:
            record, provisioned = materializer.ensure_closure(resource_type, name)
            _track_ephemeral(context, materializer, provisioned)
            _report_provisioned(request.node.nodeid, provisioned)
            return record

        return provision

    _factory.__name__ = resource_type
    _factory.__doc__ = f"Provision a `{resource_type}` by catalog name: {resource_type}('<name>') -> record."
    return pytest.fixture(name=resource_type)(_factory)


# Generated factories land in this module's namespace, so a type may not shadow anything here.
_MODULE_NAMES = frozenset(globals())

for _type in _BOOT.materializer.resource_types():
    if _type in _MODULE_NAMES:
        raise RuntimeError(
            f"resource type {_type!r} collides with a name the ATF plugin defines; rename the type"
        )
    globals()[_type] = _make_factory(_type)


@given(parsers.parse('the {resource_type} "{name}"'))
def _provision(context: SimpleNamespace, request: pytest.FixtureRequest, resource_type: str, name: str) -> Record:
    """`Given the account "primary"` -> provisions accounts.primary onto `context.account`."""
    engine: Materializer = request.getfixturevalue("materializer")
    if resource_type not in engine.types:
        known = ", ".join(engine.resource_types()) or "none"
        pytest.fail(f"no resource type {resource_type!r} in the catalog (known types: {known})")

    # The factory records every ephemeral resource in the closure, including ones reached
    # through a dependency rather than named here.
    record = request.getfixturevalue(resource_type)(name)
    setattr(context, resource_type, record)
    return record


def _report_provisioned(nodeid: str, provisioned: dict[str, Record]) -> None:
    """Tell whoever is watching this run what the test just had to bring into existence.

    Only when `ATF_PROGRESS_OUT` names the channel the run was launched with — under a plain
    `pytest`, nothing is written and nothing changes.
    """
    path = os.environ.get(PROGRESS_OUT)
    if not path or not provisioned:
        return
    event = {"event": "provisioned", "nodeid": nodeid, "ids": sorted(provisioned)}
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")
    except OSError:
        pass


def _track_ephemeral(
    context: SimpleNamespace,
    materializer: Materializer,
    provisioned: dict[str, Record],
) -> None:
    ephemeral = materializer.ephemeral_records(provisioned)
    if not ephemeral:
        return
    tracked: list[tuple[str, Record]] = getattr(context, EPHEMERAL_ATTR, [])
    tracked.extend(ephemeral)
    setattr(context, EPHEMERAL_ATTR, tracked)


@pytest.fixture(autouse=True)
def _teardown(materializer: Materializer, context: SimpleNamespace):
    yield
    materializer.teardown(getattr(context, EPHEMERAL_ATTR, []))
