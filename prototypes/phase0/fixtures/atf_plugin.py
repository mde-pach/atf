"""Prototype for MIGRATION.md §1.2 — a resource is a pytest fixture, and two of a kind is an error.

Three things are being asked of real pytest here:

1. Can ATF mint a fixture per declared instance *and* a fixture per kind, by name, at run time?
2. Can "the one in scope" be decided **at collection**, before any test body runs?
3. When two of a kind are in scope, can the run be stopped with a message naming the candidates?

The design this arrives at is that **the collection pass decides and the fixture obeys**. Resolution
is worked out once, statically, per test — which is also what `arrange.md#asking-for-one` promises
the editor: "each parameter shows what it will resolve to for the scenario it sits in".
"""

from __future__ import annotations

import re
import types
from typing import Any

import pytest

# --- The module scan: an instance's name is its variable's name ---------------------------------
import resources
from atf_registry import matching_step
from lineage.explicit import DECLARED, INSTANCES, scan

scan(resources)


def kind_fixture_name(cls: type) -> str:
    """`Owner` -> `owner`, `TodoList` -> `todo_list` — the name a scenario says."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()


KINDS: dict[str, type] = {kind_fixture_name(cls): cls for cls in DECLARED.values()}

# (nodeid, parameter name) -> the instance name it resolves to, or "" for "build one".
DECISIONS: dict[tuple[str, str], str] = {}


# --- Minting the fixtures -----------------------------------------------------------------------


def _instance_fixture(name: str):
    def fixture() -> Any:
        return INSTANCES[name]

    fixture.__name__ = name
    fixture.__doc__ = f"The declared resource `{name}`."
    return pytest.fixture(name=name)(fixture)


def _kind_fixture(fixture_name: str, cls: type):
    def fixture(request: pytest.FixtureRequest) -> Any:
        chosen = DECISIONS.get((request.node.nodeid, fixture_name), "")
        if chosen:
            return INSTANCES[chosen]
        factory = getattr(cls, "factory", None)
        if factory is None:
            raise pytest.UsageError(
                f"{request.node.nodeid}: '{fixture_name}' asks for a {cls.__name__}, nothing is in "
                f"scope, and {cls.__name__} has no factory. Name the one you mean."
            )
        # What a factory needs is what the kind's `depends_on` says it needs — not what its own
        # signature happens to be annotated with. Each is asked for by its kind's fixture name, so
        # anything already in scope answers it before another one is built.
        needs = [kind_fixture_name(entry) for entry in cls.__atf__.depends_on if isinstance(entry, type)]
        return factory(**{need: request.getfixturevalue(need) for need in needs})

    fixture.__name__ = fixture_name
    fixture.__doc__ = f"The {cls.__name__} in scope, or one the factory builds."
    return pytest.fixture(name=fixture_name)(fixture)


def pytest_configure(config: pytest.Config) -> None:
    """Register one fixture per instance and one per kind, before collection."""
    plugin = types.ModuleType("atf_resource_fixtures")
    for name in INSTANCES:
        setattr(plugin, name, _instance_fixture(name))
    for fixture_name, cls in KINDS.items():
        if fixture_name in INSTANCES:
            raise pytest.UsageError(
                f"the instance '{fixture_name}' has the same name as the kind {cls.__name__} asks for"
            )
        setattr(plugin, fixture_name, _kind_fixture(fixture_name, cls))
    config.pluginmanager.register(plugin, "atf-resource-fixtures")


# --- The collection pass ------------------------------------------------------------------------

GIVEN_NAMED = re.compile(r'(?:the|an?) (\w+) "([^"]+)"')


def _arranged_by_scenario(item: pytest.Item) -> list[str]:
    """The instances a scenario's `Given` lines name, read at collection from the parsed feature.

    `And` continues the previous keyword, which pytest-bdd has already worked out into `step.type`.
    """
    scenario = getattr(getattr(item, "function", None), "__scenario__", None)
    if scenario is None:
        return []
    names = []
    for step in getattr(scenario, "steps", []):
        if getattr(step, "type", "") != "given":
            continue
        found = GIVEN_NAMED.match(step.name)
        if found and found.group(2) in INSTANCES:
            names.append(found.group(2))
    return names


def _in_scope(item: pytest.Item) -> list[str]:
    """Every instance this test has arranged: asked for by name, or named by its scenario."""
    closure = list(getattr(item, "fixturenames", []))
    by_signature = [name for name in closure if name in INSTANCES]
    return list(dict.fromkeys(by_signature + _arranged_by_scenario(item)))


def _requested(item: pytest.Item) -> set[str]:
    """Every fixture name this test asks for, whichever surface it is written on.

    A plain test's requests are its closure. A scenario's are *not* — pytest-bdd asks for a step's
    parameters while the step runs, so they never reach `item.fixturenames`. They are recovered by
    matching each sentence to the step ATF registered for it and reading that function's signature.
    """
    requested = set(getattr(item, "fixturenames", []))
    scenario = getattr(getattr(item, "function", None), "__scenario__", None)
    if scenario is None:
        return requested
    for step in getattr(scenario, "steps", []):
        definition = matching_step(step.type, step.name)
        if definition is None:
            continue
        requested.update(definition.parameters)
    return requested


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Decide every kind parameter now, and refuse the run if any of them is ambiguous.

    Every problem is collected before raising, so one run reports them all rather than one.
    """
    problems: list[str] = []
    for item in items:
        arranged = _in_scope(item)
        requested = _requested(item)
        for fixture_name, cls in KINDS.items():
            if fixture_name not in requested:
                continue
            candidates = [name for name in arranged if type(INSTANCES[name]) is cls]
            if len(candidates) > 1:
                problems.append(
                    f"{item.nodeid}\n"
                    f"    '{fixture_name}' is ambiguous: {len(candidates)} of kind {cls.__name__} "
                    f"are in scope — {', '.join(sorted(candidates))}.\n"
                    f"    Ask for the one you mean by name."
                )
            elif not candidates and not hasattr(cls, "factory"):
                problems.append(
                    f"{item.nodeid}\n"
                    f"    '{fixture_name}' asks for a {cls.__name__}, nothing is in scope, and "
                    f"{cls.__name__} has no factory.\n"
                    f"    Name the one you mean, or give {cls.__name__} a factory."
                )
            else:
                DECISIONS[(item.nodeid, fixture_name)] = candidates[0] if candidates else ""

    if problems:
        raise pytest.UsageError("two of a kind in scope:\n\n" + "\n\n".join(problems))


def pytest_report_header(config: pytest.Config) -> list[str]:
    return [
        f"atf: {len(INSTANCES)} instances {sorted(INSTANCES)}",
        f"atf: {len(KINDS)} kinds {sorted(KINDS)}",
    ]
