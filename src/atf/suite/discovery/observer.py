"""Watches a pytest collection and writes down what it saw — it collects, and never runs."""


import json
import os
import re

_PATH = os.environ["ATF_OBSERVE_OUT"]
_DATA = {"items": {}, "fixtures": {}, "steps": [], "described": {}}
_CAPTURE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::[^{}]*)?\}")


def _step_fixtures(item, scenario):
    """The fixtures each step definition declares, resolved without running anything.

    pytest-bdd registers each step as a fixture whose function is a wrapper taking no arguments,
    so the real signature lives on the step context. Parser arguments (`{name}` captures) are not
    fixtures and are excluded.
    """
    import inspect

    names = set()
    try:
        from pytest_bdd.scenario import find_fixturedefs_for_step
    except ImportError:
        return names

    manager = getattr(item.session, "_fixturemanager", None)
    if manager is None:
        return names

    for step in getattr(scenario, "steps", []) or []:
        try:
            for fixturedef in find_fixturedefs_for_step(step, manager, item) or []:
                names.update(getattr(fixturedef, "argnames", ()) or ())
                context = getattr(fixturedef.func, "_pytest_bdd_step_context", None)
                if context is None:
                    continue
                captured = set(context.parser.parse_arguments(step.name) or {})
                names.update(
                    parameter
                    for parameter in inspect.signature(context.step_func).parameters
                    if parameter not in captured
                )
        except Exception:
            continue
    return names


def _expression(parser):
    """The raw expression a step parser was built from.

    Probed, never assumed — pytest-bdd spells it differently by version and parser class: `name` on
    every `StepParser`, `pattern` where one is exposed, the compiled `regex` for a `parsers.re`
    step, and `str()` as the answer of last resort.
    """
    for attribute in ("name", "pattern"):
        value = getattr(parser, attribute, None)
        if isinstance(value, str) and value:
            return value
    value = getattr(getattr(parser, "regex", None), "pattern", None)
    if isinstance(value, str) and value:
        return value
    return str(parser)


def _capture_names(parser, expression):
    """The parameters a step takes, in the order the wording puts them."""
    groups = getattr(getattr(parser, "regex", None), "groupindex", None) or {}
    if groups:
        return sorted(groups, key=lambda name: groups[name])
    ordered = []
    for name in _CAPTURE.findall(expression):
        if name not in ordered:
            ordered.append(name)
    return ordered


def _step_definitions(session):
    """Every step definition registered anywhere in this suite, used or not.

    pytest-bdd stores each one as a fixture named `pytestbdd_stepdef_*` whose function carries a
    `_pytest_bdd_step_context`, so the fixture registry after collection is the whole vocabulary
    the project offers — including steps no scenario has reached for yet, which is exactly what a
    composer needs to show. Every failure here is swallowed: discovery runs on every page render.
    """
    found = []
    manager = getattr(session, "_fixturemanager", None)
    if manager is None:
        return found
    try:
        from pytest_bdd.steps import StepNamePrefix

        prefix = StepNamePrefix.step_def.value
    except Exception:
        prefix = "pytestbdd_stepdef"

    for name, definitions in list((getattr(manager, "_arg2fixturedefs", None) or {}).items()):
        if not str(name).startswith(prefix):
            continue
        for fixturedef in definitions or []:
            try:
                context = getattr(getattr(fixturedef, "func", None), "_pytest_bdd_step_context", None)
                if context is None:
                    continue
                function = context.step_func
                # pytest-bdd registers its own `trace` step for all three keywords. It is a
                # debugger hook, not part of any project's vocabulary.
                if str(getattr(function, "__module__", "")).split(".")[0] == "pytest_bdd":
                    continue
                expression = _expression(context.parser)
                # A phrase is a step ATF built from a line of YAML, so its source is that file and
                # not the module the function happens to live in. What it stands for travels with
                # it, which is where its needs come from.
                phrase = getattr(function, "__atf_phrase__", None) or {}
                found.append(
                    {
                        "keyword": context.type or "*",
                        "pattern": expression,
                        "params": _capture_names(context.parser, expression),
                        "file": phrase.get("file")
                        or getattr(getattr(function, "__code__", None), "co_filename", "")
                        or "",
                        "docstring": " ".join((getattr(function, "__doc__", "") or "").split()),
                        "expands_to": list(phrase.get("expands_to") or []),
                    }
                )
            except Exception:
                continue
    return found


def pytest_collection_modifyitems(session, config, items):
    for item in items:
        scenario = getattr(getattr(item, "obj", None), "__scenario__", None)
        fixtures = set(getattr(item, "fixturenames", []) or [])
        entry = {
            "name": item.name,
            "file": str(item.path) if getattr(item, "path", None) else "",
            "skipped": any(mark.name in ("skip", "skipif", "wip") for mark in item.iter_markers()),
        }
        if scenario is not None:
            entry["feature"] = getattr(scenario.feature, "name", "") or ""
            entry["scenario"] = getattr(scenario, "name", "") or ""
            tags = getattr(scenario, "tags", None) or set()
            entry["tags"] = sorted(tags)
            fixtures |= _step_fixtures(item, scenario)
        entry["fixtures"] = sorted(fixtures)
        _DATA["items"][item.nodeid] = entry
        _DATA["fixtures"][item.nodeid] = sorted(fixtures)


def _described(session):
    """Every fixture this suite offers, with its docstring and its scope.

    Read from the fixture manager, which is right here holding the same objects `pytest --fixtures`
    would format in a second process.

    A fixture may be registered under one name several times (a plugin's, then a conftest's
    overriding it); the last definition is the one that wins at run time, so it is the one described.
    """
    manager = getattr(session, "_fixturemanager", None)
    found = {}
    for name, definitions in getattr(manager, "_arg2fixturedefs", {}).items():
        for definition in definitions:
            function = getattr(definition, "func", None)
            doc = (getattr(function, "__doc__", "") or "").strip()
            found[name] = {
                # One line, as the cockpit shows it: a fixture's first sentence is what it is for.
                "doc": " ".join(doc.split()),
                "scope": str(getattr(definition, "scope", "function") or "function"),
            }
    return found


def pytest_sessionfinish(session, exitstatus):
    # Read after collection has finished, so every steps module has been imported and registered.
    try:
        _DATA["steps"] = _step_definitions(session)
    except Exception:
        _DATA["steps"] = []
    try:
        _DATA["described"] = _described(session)
    except Exception:
        _DATA["described"] = {}
    with open(_PATH, "w") as handle:
        json.dump(_DATA, handle)
