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

from . import collect, phrasebook
from .adapters import Record, can_show, why_unavailable
from .bootstrap import Boot, bootstrap
from .catalog import natural_keys
from .context import EPHEMERAL_ATTR, Context, Recogniser
from .materializer import Materializer
from .placeholders import PLACEHOLDER_RE, Unresolved
from .runner import PROGRESS_OUT

# The read-and-compare steps, and the ones that act on an interface, are plugins of their own so
# that their step definitions land in their own module namespaces. pytest reads `pytest_plugins`
# from any plugin it registers, so a suite that enables `atf.plugin` gets them without naming more.
pytest_plugins = ["atf.steps", "atf.ui"]

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
    ) -> Callable[..., Record]:
        def provision(name: str, overrides: Record | None = None) -> Record:
            record, provisioned = materializer.ensure_closure(resource_type, name, overrides)
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
    return _make(context, request, resource_type, name, None)


@given(parsers.parse('the {resource_type} "{name}" but:'))
def _provision_varied(
    context: Context, request: pytest.FixtureRequest, resource_type: str, name: str, datatable: Any = None
) -> Record:
    """The same resource, with some of its body written differently for this scenario only.

    The alternative is a second catalog node per variation, which is Object Mother: a global set of
    named factories where every variation needs a new one and every scenario couples to a specific
    one. One node, and the scenarios that need something different say so where they need it.
    """
    return _make(context, request, resource_type, name, _overrides(datatable, resource_type, name))


@given(parsers.parse('a fresh {resource_type} "{name}"'))
def _provision_fresh(context: Context, request: pytest.FixtureRequest, resource_type: str, name: str) -> Record:
    """`Given a fresh todo_list "groceries"` -> a groceries list this scenario alone holds."""
    return _make_fresh(context, request, resource_type, name, None)


@given(parsers.parse('a fresh {resource_type} "{name}" but:'))
def _provision_fresh_varied(
    context: Context, request: pytest.FixtureRequest, resource_type: str, name: str, datatable: Any = None
) -> Record:
    """The same isolated instance, with some of its body written differently for this scenario.

    It means what `but:` means everywhere else — this node's body, varied for one scenario — with
    one addition it gets for free: a field the table writes is taken *exactly* as written, including
    a natural key. That is how a scenario says what makes its copy different when appending to the
    written key would spoil it, which is what happens to anything with a shape, an email above all.
    """
    return _make_fresh(context, request, resource_type, name, _overrides(datatable, resource_type, name))


def _overrides(datatable: Any, resource_type: str, name: str) -> Record:
    if not datatable:
        pytest.fail(
            f'the {resource_type} "{name}" but: — `but` needs a table of what to write differently, '
            "below it."
        )
    varied: Record = {}
    for row in datatable:
        cells = [str(cell) for cell in row]
        if len(cells) != 2:
            pytest.fail(
                f"every row takes a field and what to put in it — two cells. "
                f"Got {len(cells)}: {' | '.join(cells)}"
            )
        varied[cells[0].strip()] = cells[1]
    return varied


def _make(
    context: Context,
    request: pytest.FixtureRequest,
    resource_type: str,
    name: str,
    overrides: Record | None,
) -> Record:
    engine: Materializer = request.getfixturevalue("materializer")
    if resource_type not in engine.types:
        known = ", ".join(engine.resource_types()) or "none"
        pytest.fail(f"no resource type {resource_type!r} in the catalog (known types: {known})")

    # The factory records every ephemeral resource in the closure, including ones reached
    # through a dependency rather than named here.
    record = request.getfixturevalue(resource_type)(name, overrides)
    setattr(context, resource_type, record)
    # The record itself does not say which catalog node it came from, and this is the one place
    # that knows. Everything downstream reads it from the slot rather than guessing at it.
    if isinstance(context, Context):
        context.note(resource_type, resource_type=resource_type, node_id=engine.resolve_id(resource_type, name))
    _note_what_is_showing(context, engine, resource_type)
    return record


def _make_fresh(
    context: Context,
    request: pytest.FixtureRequest,
    resource_type: str,
    name: str,
    overrides: Record | None,
) -> Record:
    """Provision an instance of a catalog node that belongs to this scenario and goes with it.

    The two refusals are here rather than in the engine because a refusal is a sentence somebody
    reads, and this is the only place that knows what they wrote. Both are answers, not obstacles:
    there is no isolated instance of a resource ATF cannot create, and no telling two instances
    apart where nothing distinguishes them.
    """
    engine: Materializer = request.getfixturevalue("materializer")
    if resource_type not in engine.types:
        known = ", ".join(engine.resource_types()) or "none"
        pytest.fail(f"no resource type {resource_type!r} in the catalog (known types: {known})")

    node_id = engine.resolve_id(resource_type, name)
    can, why = engine.provisionable(node_id)
    if not can:
        # The three nodes nothing can provision are exactly the three there can be no fresh instance
        # of, and `provisionable` is where ATF already decides that — including for the cockpit's
        # "create it" button, which is the same question asked by a different surface.
        pytest.fail(
            f'a fresh {resource_type} "{name}": {why}. '
            f'Say `Given the {resource_type} "{name}"`, which is how this one is asked for.'
        )

    fields, cannot = engine.key_of_its_own(engine.node(node_id))
    if not fields and not overrides:
        pytest.fail(
            f'a fresh {resource_type} "{name}": {cannot}. '
            f"Give the type a `natural_key` ATF can vary, or say what makes this one different with "
            f'`Given a fresh {resource_type} "{name}" but:` and a table under it.'
        )

    record, provisioned = engine.ensure_fresh(resource_type, name, overrides)
    # Its dependencies were provisioned as usual, so an ephemeral one among them is tracked as
    # usual; the instance itself is tracked whatever its catalog says, because being taken away with
    # the scenario is the whole of what was asked for.
    _track_ephemeral(context, engine, provisioned)
    _remember(context, [(node_id, record)])
    _emit({"event": "provisioned", "nodeid": request.node.nodeid, "ids": [node_id]})

    setattr(context, resource_type, record)
    context.note(resource_type, resource_type=resource_type, node_id=node_id)
    _note_what_is_showing(context, engine, resource_type)
    return record


def _note_what_is_showing(context: Context, engine: Materializer, resource_type: str) -> None:
    """Remember the system this scenario is now looking at, for the steps that claim about a page.

    A suite may configure more than one — `html` reads what a server sent and `browser` reads what
    a browser ran, and a suite is entitled to both. `the button "Save" is showing` must not have to
    say which, so the `Given` that opened a page settles it: the resource the scenario named already
    said which system it belongs to.

    Underscored, so it is ATF's bookkeeping rather than a slot a scenario can make a claim about.
    """
    system = str(engine.types.get(resource_type, {}).get("system", ""))
    adapter = engine.adapters.get(system)
    if adapter is not None and can_show(adapter):
        context._showing = adapter  # noqa: SLF001 - `context` is ATF's own object, and this is ATF


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


def pytest_collect_file(file_path, parent):
    """Collect a `.feature` nobody bound, so a feature needing no step code needs no file beside it.

    See [collect.py](collect.py) for what such a feature can reach — the short answer is ATF's own
    steps, this suite's phrases, and anything a `conftest.py` above it declares.
    """
    return collect.collect(file_path, parent, _BOOT.manifest.specs_dir)


def pytest_collection_modifyitems(items) -> None:
    """Skip what needs a system this machine has not got, and say what is missing.

    `requires: {browser: browser}` in the manifest says a `@browser` scenario cannot run where the
    `browser` system is unavailable. Every suite used to write this itself, as a raw
    `pytest_collection_modifyitems` in a `conftest.py` that otherwise never mentions pytest — and
    the alternative to writing it is worse: the scenarios fail, and a suite that is red on a
    machine without a browser stops being read at all.

    A skip, never a pass. The scenario did not run, and the report says so, with the reason.
    """
    requires = _BOOT.manifest.requires
    if not requires:
        return

    reasons: dict[str, str] = {}
    for tag, system in requires.items():
        adapter = _BOOT.materializer.adapters.get(system)
        if adapter is None:
            reasons[tag] = f"this environment configures no {system!r} system"
            continue
        why = why_unavailable(adapter)
        if why:
            reasons[tag] = why

    if not reasons:
        return
    for item in items:
        for tag in {mark.name for mark in item.iter_markers()} & set(reasons):
            item.add_marker(pytest.mark.skip(reason=f"needs {requires[tag]}: {reasons[tag]}"))


def pytest_sessionfinish(session, exitstatus) -> None:
    """Let every adapter release what it is holding, now that no scenario will ask for anything.

    `Closeable` has been part of the SPI since the browser adapter shipped — a REST adapter holds an
    HTTP client, a browser adapter holds a browser and the process driving it — and nothing ever
    called it. A suite that opened a page left Playwright and a Chromium running until the
    interpreter died, and an adapter of a project's own that held a socket, a tunnel or a container
    had no moment at which it was told the run was over. It has one.

    Never raises: what is being released is already finished with, and a run that passed must not go
    red on the way out. `close_adapter` swallows and logs, and this is the only caller.
    """
    _BOOT.materializer.close()


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
    _remember(context, materializer.ephemeral_records(provisioned))


def _remember(context: Context, made: list[tuple[str, Record]]) -> None:
    """Note what this scenario built for itself, so teardown knows what to take away again."""
    if not made:
        return
    tracked: list[tuple[str, Record]] = getattr(context, EPHEMERAL_ATTR, [])
    tracked.extend(made)
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
