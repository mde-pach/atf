"""ATF's pytest plugin: a fixture per resource, an item per scenario, one engine behind both."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from typing_extensions import override

from . import feature as feature_reader
from . import phrases as phrase_reader
from . import (
    reconcile,
    runtime,
    steps,
    vocabulary,  # noqa: F401 - imported so its sentences are registered
)
from .declare import declaration_of
from .environment import Ground, build_ground
from .loader import Suite, fixture_name, load_suite
from .manifest import load
from .runtime import Scope
from .steps import Sentence, Step, StepError

MARKER = "atf"


class Loaded:
    """The suite, its environment and its vocabulary — read once per session."""

    def __init__(self, root: Path | None = None) -> None:
        # `MANIFEST` is set by `atf run --config`. Without it the plugin would search upwards from
        # the working directory and find a *different* manifest — which is exactly what happens
        # when one suite runs another, and ATF's own suite does nothing else.
        chosen = load(root / "atf.yaml") if root else MANIFEST
        self.suite: Suite = load_suite(chosen)
        self.ground: Ground = build_ground(self.suite)
        _import_step_modules(self.suite)
        self.features = feature_reader.read_all(self.suite.manifest.specs)
        self.phrases = phrase_reader.collect(self.features)
        #: Everything this run has made, across every test in it. A `session` resource is made
        #: by whichever test needed it first, so the ledger cannot live on one test's scope.
        self.made: list[Any] = []

    @property
    def kinds(self) -> dict[str, type]:
        return {fixture_name(name): cls for name, cls in self.suite.kinds.items()}


def _import_step_modules(suite: Suite) -> None:
    """Import every module under `specs/` that is not a test, so its steps are registered.

    A step a suite writes has to be registered before a scenario is matched against it, and pytest
    only imports `test_*.py`. `specs/` is one flat namespace — the same one phrases live in — so a
    `steps.py` beside a feature file is found without the manifest listing it.
    """
    specs = suite.manifest.specs
    if not specs.is_dir():
        return
    root = str(specs.parent.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    for path in sorted(specs.rglob("*.py")):
        if path.name.startswith(("test_", "_")) or path.name == "conftest.py":
            continue
        name = ".".join(path.relative_to(specs.parent).with_suffix("").parts)
        if name in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)


_LOADED: Loaded | None = None
#: (nodeid, parameter) -> the resource name it resolves to, or "" for "the factory builds one".
DECISIONS: dict[tuple[str, str], str] = {}
#: What `atf run` chose, set before pytest starts. `None` means every test.
SELECTION: Any = None
#: `--no-make`: a test needing an absent resource fails, and nothing is created.
NO_MAKE: bool = False
#: Which manifest this run is against, when something other than the nearest one was named.
MANIFEST: Any = None


def loaded() -> Loaded:
    if _LOADED is None:
        raise RuntimeError("ATF's plugin was asked for the suite before pytest configured it")
    return _LOADED


# --- Registering the fixtures -----------------------------------------------------------------


def _instance_fixture(name: str):
    def fixture(atf: Scope) -> Any:
        return atf.arrange(fixture_name(declaration_of(loaded().suite.resource(name)).kind), name)

    fixture.__name__ = name
    fixture.__doc__ = f"The declared resource `{name}`, and everything its lineage needs."
    return pytest.fixture(name=name)(fixture)


def _kind_fixture(kind: str):
    def fixture(request: pytest.FixtureRequest, atf: Scope) -> Any:
        chosen = DECISIONS.get((request.node.nodeid, kind), "")
        if chosen:
            return atf.arrange(kind, chosen)
        return atf.the(kind)

    fixture.__name__ = kind
    fixture.__doc__ = f"The {kind} in scope, or one the factory builds."
    return pytest.fixture(name=kind)(fixture)


def pytest_configure(config: pytest.Config) -> None:
    """Load the suite, then mint a fixture per declared resource and per kind."""
    global _LOADED  # noqa: PLW0603 - one suite per pytest session is one process-wide fact
    _LOADED = Loaded()
    config.addinivalue_line("markers", f"{MARKER}: a scenario ATF collected from a .feature file")
    for tag in sorted({tag for f in _LOADED.features for s in f.scenarios for tag in s.tags}):
        config.addinivalue_line("markers", f"{tag}: a tag this suite writes on scenarios")
    # A tag on a scenario is registered as a pytest marker.
    for tag in sorted({tag for f in _LOADED.features for s in f.scenarios for tag in s.tags}):
        config.addinivalue_line("markers", f"{tag}: a tag on one of this suite's scenarios")

    import types

    plugin = types.ModuleType("atf_resource_fixtures")
    for name in _LOADED.suite.instances:
        setattr(plugin, name, _instance_fixture(name))
    for kind in _LOADED.kinds:
        setattr(plugin, kind, _kind_fixture(kind))
    config.pluginmanager.register(plugin, "atf-resource-fixtures")


@pytest.fixture
def atf() -> Any:
    """What this test is holding: what it arranged, and what its actions produced."""
    state = runtime.start(Scope(suite=loaded().suite, ground=loaded().ground, run=loaded().made))
    yield state
    # Function scope ends here; session scope ends with the run. Persistent is never torn down.
    reconcile.teardown(state.ground, reconcile.scoped(state.made, "function"))
    runtime.finish()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Remove what the run owns, in reverse lineage order. Persistent resources are not touched."""
    if _LOADED is None:
        return
    reconcile.teardown(_LOADED.ground, reconcile.scoped(_LOADED.made, "session"))


@pytest.fixture
def shell(atf: Scope) -> Any:
    """Run a command line against the current environment, through its `prefix`."""
    adapter = atf.ground.adapters.get("command")
    if adapter is None:
        raise pytest.UsageError(
            f"the `shell` fixture needs a `command:` block in the "
            f"{atf.ground.config.name!r} environment"
        )
    return adapter.shell


# --- Collecting scenarios ---------------------------------------------------------------------


def pytest_collect_file(parent: Any, file_path: Path) -> Any:
    if file_path.suffix == ".feature":
        return FeatureFile.from_parent(parent, path=file_path)
    return None


class FeatureFile(pytest.File):
    """One `.feature` file, as a collector of the scenarios in it."""

    @override
    def collect(self):
        parsed = feature_reader.read(Path(self.path))
        for scenario in parsed.scenarios:
            if scenario.is_phrase:
                continue  # vocabulary, never a test
            yield ScenarioItem.from_parent(self, name=_test_name(scenario.name), scenario=scenario)


class ScenarioItem(pytest.Item):
    """One scenario. Its sentences are resolved at collection and run here."""

    def __init__(self, *, scenario: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.scenario = scenario
        self.add_marker(MARKER)
        for tag in scenario.tags:
            self.add_marker(tag)
        self.sentences: list[Sentence] = []

    def resolve(self) -> list[Sentence]:
        """Expand phrases, then bind every line to the step that answers it."""
        expanded = phrase_reader.expand(self.scenario, loaded().phrases)
        self.sentences = [
            Sentence(keyword=line.keyword, text=line.text, line=line.number).resolve()
            for line in expanded.lines
        ]
        return self.sentences

    @override
    def runtest(self) -> None:
        state = runtime.start(Scope(suite=loaded().suite, ground=loaded().ground, run=loaded().made))
        try:
            for sentence in self.sentences or self.resolve():
                _run_sentence(state, sentence)
        finally:
            reconcile.teardown(state.ground, reconcile.scoped(state.made, "function"))
            runtime.finish()

    @override
    def repr_failure(self, excinfo: Any, style: Any = None) -> str:
        """Name the sentence, not the frame. Every failure names your sentence."""
        where = getattr(excinfo.value, "atf_sentence", None)
        head = f"{self.scenario.path}:{self.scenario.number}  Scenario: {self.scenario.name}"
        if where is not None:
            return f"{head}\n  {where.keyword.title()} {where.text}\n\n{excinfo.value}"
        return f"{head}\n\n{excinfo.value}"

    @override
    def reportinfo(self):
        return self.path, self.scenario.number - 1, f"Scenario: {self.scenario.name}"


def _run_sentence(state: Scope, sentence: Sentence) -> None:
    step: Step | None = sentence.step
    if step is None:
        raise StepError(steps.undefined(sentence.keyword, sentence.text))
    if getattr(step.function, "__atf_claim__", None) is not None:
        from .registries import resolve_claim_arguments  # noqa: PLC0415

        arguments = resolve_claim_arguments(step, sentence.values, state)
    else:
        arguments = dict(sentence.values)
        for name in step.parameters:
            arguments[name] = _supply(state, name)
    try:
        result = step.function(**arguments)
    except Exception as exc:
        setattr(exc, "atf_sentence", sentence)  # noqa: B010 - the sentence travels with the failure
        raise
    if step.target:
        state.remember(step.target, result)


def _supply(state: Scope, name: str) -> Any:
    """What a step asks for, from inside a scenario. The same names a pytest function may take."""
    if name == "atf":
        return state
    if name == "shell":
        adapter = state.ground.adapters.get("command")
        if adapter is None:
            raise StepError(
                f"this sentence needs `shell`, and the {state.ground.config.name!r} environment has "
                f"no `command:` block"
            )
        return adapter.shell
    if name in state.suite.instances:
        return state.arrange(fixture_name(declaration_of(state.suite.resource(name)).kind), name)
    if name in loaded().kinds:
        return state.the(name)
    raise StepError(f"a step asks for {name!r}, and nothing declares it")


def _test_name(title: str) -> str:
    """A scenario's identity is its own title.

    `the-record.md` writes it as `specs/lists.feature::a list belongs to its owner`, so that is what
    a report, history and `--failed` all carry. Only the characters pytest uses to build a node id
    are replaced.
    """
    cleaned = re.sub(r"[\[\]:]+", " ", title.strip()).strip()
    return cleaned or "scenario"


# --- The collection pass ------------------------------------------------------------------------


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Narrow to what was selected, then decide every kind parameter in what is left.

    Selection comes first: only what this run will execute is checked.
    """
    if SELECTION is not None:
        kept, dropped = _apply_selection(items)
        if dropped:
            config.hook.pytest_deselected(items=dropped)
            items[:] = kept

    problems: list[str] = []
    kinds = loaded().kinds

    for item in items:
        try:
            requested, arranged = _asked_and_arranged(item)
        except (StepError, phrase_reader.PhraseError) as exc:
            problems.append(f"{item.nodeid}\n    {exc}")
            continue

        for kind in kinds:
            if kind not in requested:
                continue
            candidates = [name for name in arranged if _kind_of(name) == kind]
            if len(candidates) > 1:
                problems.append(
                    f"{item.nodeid}\n"
                    f"    '{kind}' is ambiguous: {len(candidates)} of that kind are in scope — "
                    f"{', '.join(sorted(candidates))}.\n"
                    f"    Ask for the one you mean by name."
                )
            elif not candidates and not hasattr(kinds[kind], "factory"):
                problems.append(
                    f"{item.nodeid}\n"
                    f"    '{kind}' asks for a {kinds[kind].__name__}, nothing is in scope, and it "
                    f"has no factory.\n    Name the one you mean, or give it a factory."
                )
            else:
                DECISIONS[(item.nodeid, kind)] = candidates[0] if candidates else ""

    if problems:
        raise pytest.UsageError(
            "this suite cannot be run as written:\n\n" + "\n\n".join(problems)
        )


def _apply_selection(items: list[pytest.Item]) -> tuple[list[pytest.Item], list[pytest.Item]]:
    """Split the collected tests into what this run asked for and what it did not."""
    suite = loaded().suite
    wanted: set[str] | None = None
    if SELECTION.select:
        from .runner import resources_reaching

        wanted = resources_reaching(suite, SELECTION.resource, downstream=SELECTION.downstream)

    kept: list[pytest.Item] = []
    dropped: list[pytest.Item] = []
    for item in items:
        if _chosen(item, wanted):
            kept.append(item)
        else:
            dropped.append(item)
    return kept, dropped


def _chosen(item: pytest.Item, wanted: set[str] | None) -> bool:
    if SELECTION.tags and not any(item.get_closest_marker(tag) for tag in SELECTION.tags):
        return False
    if SELECTION.failed and item.nodeid not in SELECTION.failed_ids:
        return False
    if wanted is not None:
        try:
            _, arranged = _asked_and_arranged(item)
        except Exception:  # noqa: BLE001 - a test that cannot be read is not one this slice chose
            return False
        if not wanted & set(arranged):
            return False
    return True


def _kind_of(name: str) -> str:
    return fixture_name(declaration_of(loaded().suite.resource(name)).kind)


def _asked_and_arranged(item: pytest.Item) -> tuple[set[str], list[str]]:
    """What this test asks for, and which resources it has arranged — both known at collection."""
    if isinstance(item, ScenarioItem):
        sentences = item.resolve()
        requested = {name for sentence in sentences for name in sentence.requests}
        arranged = [
            name
            for sentence in sentences
            if sentence.keyword == steps.GIVEN
            for name in _named_in(sentence)
        ]
        # A scenario's steps also reach kinds through `atf`, which is how `the {kind}` is written.
        requested |= {
            values.get("kind", "")
            for sentence in sentences
            if (values := sentence.values) and "kind" in values and "name" not in values
        }
        return requested, arranged

    closure = set(getattr(item, "fixturenames", []))
    return closure, [name for name in closure if name in loaded().suite.instances]


def _named_in(sentence: Sentence) -> list[str]:
    name = sentence.values.get("name")
    return [name] if name and name in loaded().suite.instances else []

