"""The pytest plugin: context, generated resource factories, the steps ATF defines, teardown.

Enable it from a consuming project's `conftest.py`:

    pytest_plugins = ["atf.plugin"]
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

import pytest
from pytest_bdd import given, parsers
from pytest_bdd import step as register_step

from . import phrasebook
from .adapters import Record
from .bootstrap import Boot, bootstrap
from .catalog import natural_keys
from .context import EPHEMERAL_ATTR, Context, Recogniser
from .materializer import Materializer
from .placeholders import PLACEHOLDER_RE, Unresolved
from .runner import PROGRESS_OUT

# The read-and-compare steps are a plugin of their own so that the step definitions land in their
# own module namespace. pytest reads `pytest_plugins` from any plugin it registers, so a suite that
# enables `atf.plugin` gets them without naming a second thing.
pytest_plugins = ["atf.steps"]

_BOOT: Boot = bootstrap()


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
def context(materializer: Materializer) -> Context:
    """The per-scenario scratchpad: steps write what they create and read what they need."""
    # A new context is a new scenario, which is the lifetime a generated value — and a looked-up
    # identity — is held for.
    materializer.forget_scenario()
    return Context(recognise=recogniser(materializer))


def recogniser(engine: Materializer) -> Recogniser:
    """Which resource type a record the suite produced looks like — or nothing, when unsure.

    A guess, and only ever used to describe what a scenario is holding. It answers only when
    exactly one type fits, because a wrong label is worse than no label: two types matching means
    the record does not say which it is.
    """

    def recognise(record: Record) -> str:
        fits = [name for name, entry in sorted(engine.types.items()) if _fits(entry, record)]
        return fits[0] if len(fits) == 1 else ""

    return recognise


def _fits(entry: dict[str, Any], record: Record) -> bool:
    """A record fits a type when it carries the type's identity and everything it is known by."""
    keys = natural_keys(entry)
    if not keys:
        return False
    ref_field = entry.get("ref_field")
    remote = [str(ref_field)] if (ref_field and len(keys) == 1) else keys
    return str(entry.get("id_field", "id")) in record and all(key in record for key in remote)


def _make_factory(resource_type: str) -> Any:
    def _factory(
        request: pytest.FixtureRequest, materializer: Materializer, context: Context
    ) -> Callable[[str], Record]:
        def provision(name: str) -> Record:
            record, provisioned = materializer.ensure_closure(resource_type, name)
            _track_ephemeral(context, materializer, provisioned)
            if provisioned:
                _emit({"event": "provisioned", "nodeid": request.node.nodeid, "ids": sorted(provisioned)})
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
def _provision(context: Context, request: pytest.FixtureRequest, resource_type: str, name: str) -> Record:
    """`Given the account "primary"` -> provisions accounts.primary onto `context.account`."""
    engine: Materializer = request.getfixturevalue("materializer")
    if resource_type not in engine.types:
        known = ", ".join(engine.resource_types()) or "none"
        pytest.fail(f"no resource type {resource_type!r} in the catalog (known types: {known})")

    # The factory records every ephemeral resource in the closure, including ones reached
    # through a dependency rather than named here.
    record = request.getfixturevalue(resource_type)(name)
    setattr(context, resource_type, record)
    # The record itself does not say which catalog node it came from, and this is the one place
    # that knows. Everything downstream reads it from the slot rather than guessing at it.
    if isinstance(context, Context):
        context.note(resource_type, resource_type=resource_type, node_id=engine.resolve_id(resource_type, name))
    return record


# ---- the phrasebook --------------------------------------------------------
#
# Registered here, at module level and in a loop, for the same reason the factories above are:
# pytest-bdd injects a step's fixture into the *calling module's* namespace, so registering from
# inside a function would put it where pytest never looks.

# `parsers.parse`, never the bare string pytest-bdd would otherwise assume: a bare string is an
# exact match, and `it is refused because "{reason}"` would then only ever match a scenario that
# wrote those braces out literally.
PHRASEBOOK = phrasebook.path_for(_BOOT.manifest.specs_dir)

for _phrase in phrasebook.load(PHRASEBOOK):
    register_step(parsers.parse(_phrase.pattern), type_=None)(phrasebook.make_step(_phrase, PHRASEBOOK))


def pytest_bdd_before_step_call(request, feature, scenario, step, step_func, step_func_args) -> None:
    """Resolve `${...}` in every value a step was handed, whoever wrote the step.

    Gherkin has no way to say "a fresh company name", so a value written between quotes is the
    only place a generated one can come from. Doing it here rather than inside ATF's own steps is
    what makes it true of *any* step: `When I rename it to "${fake:company}"` works in a step the
    project wrote this morning, with nothing added to it.

    pytest-bdd passes this the same dict it is about to call the step with, so resolving in place
    is all there is to it. One evaluation per scenario means the `Then` that checks the rename
    writes the same expression and sees the same answer.

    It is also where the keyword is recorded, for a step that turns out to be a phrase: what it
    stands for runs as the same kind of step it was said as, and pytest-bdd gives a step function
    no way to ask which that was.
    """
    phrasebook.remember_keyword(request, str(step.type or ""))
    engine: Materializer = request.getfixturevalue("materializer")
    for name, value in list(step_func_args.items()):
        if not isinstance(value, str) or PLACEHOLDER_RE.search(value) is None:
            continue
        try:
            step_func_args[name] = str(engine.resolve(value))
        except Unresolved as exc:
            pytest.fail(f"{step.name!r}: {exc}")


def _emit(event: dict[str, Any]) -> None:
    """Tell whoever is watching this run what just happened.

    Only when `ATF_PROGRESS_OUT` names the channel the run was launched with — under a plain
    `pytest`, nothing is written and nothing changes.
    """
    path = os.environ.get(PROGRESS_OUT)
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")
    except OSError:
        pass


def _track_ephemeral(
    context: Context,
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
def _teardown(request: pytest.FixtureRequest, materializer: Materializer, context: Context):
    yield
    # What the scenario was holding when it finished: names, kinds and counts, never values. It is
    # the answer to "what was there to assert on?", which nothing could say while the context was a
    # namespace that forgot.
    if isinstance(context, Context) and context.slots:
        _emit(
            {
                "event": "held",
                "nodeid": request.node.nodeid,
                "slots": [slot.as_dict() for slot in context.slots.values()],
            }
        )
    materializer.teardown(getattr(context, EPHEMERAL_ATTR, []))
