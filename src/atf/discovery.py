"""Turns a project into the structured model the cockpit renders.

Specs come from a static parse of the `.feature` files; tests and fixtures come from pytest
itself, because pytest-bdd only resolves step fixtures while a run is happening.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .catalog import Node, find_node

PROVISION_RE = re.compile(r'\bthe ([A-Za-z_][A-Za-z0-9_]*) "([^"]+)"')
_STEP_KEYWORDS = ("Given", "When", "Then", "And", "But", "*")
_COLLECT_TIMEOUT = 300

# ATF's own generic provisioning step, defined in `plugin.py`. It is the only step definition the
# framework itself contributes, and the composer offers it as a resource picker rather than as a
# line of wording, so it must be recognisable by pattern here.
PROVISION_PATTERN = 'the {resource_type} "{name}"'

GIVEN, WHEN, THEN = "given", "when", "then"
ANY_KEYWORD = "*"
_KEYWORDS = frozenset({GIVEN, WHEN, THEN, ANY_KEYWORD})

# A `{capture}` in a step pattern, with the optional `:format` pytest-bdd's parse parser allows.
CAPTURE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::[^{}]*)?\}")


@dataclass
class Step:
    keyword: str
    text: str
    resources: list[str] = field(default_factory=list)


@dataclass
class Spec:
    id: str
    feature: str
    scenario: str
    narrative: str = ""
    file: str = ""
    line: int = 0
    steps: list[Step] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    skipped: bool = False
    test_ids: list[str] = field(default_factory=list)
    examples: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Test:
    id: str
    nodeid: str
    name: str
    params: str = ""
    file: str = ""
    covers: str = ""
    resources: list[str] = field(default_factory=list)
    fixtures: list[str] = field(default_factory=list)
    skipped: bool = False


@dataclass
class Fixture:
    name: str
    doc: str = ""
    scope: str = "function"
    used_by: list[str] = field(default_factory=list)
    generated: bool = False


@dataclass
class StepDef:
    """One step definition the project registers — the vocabulary a scenario may be written in.

    `pattern` is the parser's raw expression exactly as the author wrote it, so it is both what a
    picker shows and what a composed step's wording is built from.

    `needs` and `produces` are what the step reads from and writes to the per-scenario context,
    read out of its source. They are what lets an interface offer only the steps a scenario can
    actually use, instead of letting someone compose one that fails at the first `When`.
    """

    keyword: str
    pattern: str
    params: list[str] = field(default_factory=list)
    file: str = ""
    docstring: str = ""
    needs: list[str] = field(default_factory=list)
    produces: list[str] = field(default_factory=list)


@dataclass
class Discovery:
    specs: list[Spec] = field(default_factory=list)
    tests: list[Test] = field(default_factory=list)
    fixtures: list[Fixture] = field(default_factory=list)
    steps: list[StepDef] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def steps_for(self, keyword: str) -> list[StepDef]:
        """The definitions a picker for one keyword should offer.

        A `@step` registered without a type matches any keyword, so it is offered under all three.
        ATF's generic provisioning step is offered as `given` only: `When the account "primary"` is
        legal Gherkin but never what anyone means, and a composer that offers it twice teaches the
        wrong model.
        """
        wanted = keyword.lower()
        offered = [step for step in self.steps if step.keyword in {wanted, ANY_KEYWORD}]
        if wanted == GIVEN:
            return offered
        return [step for step in offered if step.pattern != PROVISION_PATTERN]

    def spec(self, spec_id: str) -> Spec | None:
        return next((spec for spec in self.specs if spec.id == spec_id), None)

    def test(self, test_id: str) -> Test | None:
        return next((test for test in self.tests if test.id == test_id), None)

    def fixture(self, name: str) -> Fixture | None:
        return next((fixture for fixture in self.fixtures if fixture.name == name), None)

    def tests_for_spec(self, spec_id: str) -> list[Test]:
        return [test for test in self.tests if test.covers == spec_id]

    def tests_for_resource(self, node_id: str) -> list[Test]:
        return [test for test in self.tests if node_id in test.resources]

    def specs_for_resource(self, node_id: str) -> list[Spec]:
        return [spec for spec in self.specs if node_id in spec.resources]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-") or "untitled"


def discover(
    specs_dir: Path,
    nodes: dict[str, Node],
    resource_types: set[str],
    env: str,
    project_root: Path | None = None,
) -> Discovery:
    specs = parse_specs(specs_dir, nodes, resource_types)
    result = Discovery(specs=specs)

    root = project_root or specs_dir.parent
    observed, errors = observe_pytest(root, specs_dir, env)
    result.errors = errors
    _attach_tests(result, observed, nodes)
    result.fixtures = _fixtures(root, env, observed, resource_types, errors, result.tests)
    result.steps = _step_defs(observed)
    _attach_context_use(result.steps)
    return result


# ---- step patterns ---------------------------------------------------------


def fill(pattern: str, values: dict[str, str]) -> str:
    """A step pattern with its `{captures}` replaced by the values chosen for them.

    A capture with no value keeps its placeholder, so a half-built step reads as a half-built step
    rather than as a sentence with a hole silently closed up.
    """
    return CAPTURE_RE.sub(lambda match: values.get(match.group(1)) or match.group(0), pattern)


def pattern_regex(pattern: str) -> str:
    """A step pattern as a regular expression: literals escaped, every capture a wildcard."""
    pieces = CAPTURE_RE.split(pattern)
    out = [re.escape(pieces[0])]
    for index in range(1, len(pieces), 2):
        out.append("(.+?)")
        out.append(re.escape(pieces[index + 1]))
    return "".join(out)


def matching_step(text: str, steps: list[StepDef]) -> StepDef | None:
    """The definition a step's wording resolves to, or None if this suite defines no such step.

    Matching happens here rather than in pytest-bdd because the parsers themselves live in the
    collection subprocess: what survives is the raw expression. An exact hit wins, then the
    expression read as a `{capture}` template, then the expression read as a regular expression —
    which is what a step declared with `parsers.re` needs.
    """
    for step in steps:
        if step.pattern == text:
            return step
    for as_regex in (pattern_regex, str):
        for step in steps:
            try:
                if re.fullmatch(as_regex(step.pattern), text):
                    return step
            except re.error:
                continue
    return None


# ---- what a step touches on the context ------------------------------------
#
# Steps talk to each other through `context`, and until now nothing outside the step's own body
# knew which attributes. That is the whole reason someone can compose `When I complete the task`
# without a task and only find out by running it. The source says so plainly, so read it.

# The decorators pytest-bdd registers a step with. `step` takes any keyword.
_STEP_DECORATORS = frozenset({"given", "when", "then", "step"})

# The fixture ATF's steps share. A function that does not take it cannot touch the context.
CONTEXT = "context"


def context_use(path: Path) -> dict[str, tuple[list[str], list[str]]]:
    """`{step wording: (what it reads from the context, what it writes)}` for one module.

    Read from source rather than by running anything: discovery happens on every page render, and
    against read-only environments, so it may never execute a step to find out what it does.

    Total by construction — a module that will not parse, or a step whose wording is not a literal,
    simply contributes nothing and is treated as touching nothing.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return {}

    found: dict[str, tuple[list[str], list[str]]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if CONTEXT not in {argument.arg for argument in node.args.args}:
            continue
        reads, writes = _context_names(node)
        for wording in _wordings(node):
            found[wording] = (reads, writes)
    return found


def _wordings(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """The step wordings this function is registered under — it may carry several decorators."""
    out: list[str] = []
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call) or not decorator.args:
            continue
        name = decorator.func.attr if isinstance(decorator.func, ast.Attribute) else getattr(decorator.func, "id", "")
        if name not in _STEP_DECORATORS:
            continue
        wording = _literal(decorator.args[0])
        if wording:
            out.append(wording)
    return out


def _literal(node: ast.expr) -> str:
    """A wording written plainly, or wrapped in a parser — `parsers.parse("…")` and friends."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call) and node.args:
        return _literal(node.args[0])
    return ""


def _context_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[list[str], list[str]]:
    reads: list[str] = []
    writes: list[str] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
            continue
        if node.value.id != CONTEXT or node.attr.startswith("_"):
            continue
        into = writes if isinstance(node.ctx, ast.Store) else reads
        if node.attr not in into:
            into.append(node.attr)
    # `context.result = f(context.result)` both reads and writes, and a step that rewrites what it
    # was given still needs it there first.
    return sorted(reads), sorted(writes)


def _attach_context_use(steps: list[StepDef]) -> None:
    """Read each module once, not once per step it declares."""
    from .steps import generic as _generic

    by_file: dict[str, list[StepDef]] = {}
    for step in steps:
        if step.file:
            by_file.setdefault(step.file, []).append(step)

    for file, members in by_file.items():
        use = context_use(Path(file))
        for step in members:
            reads, writes = use.get(step.pattern, ([], []))
            step.needs, step.produces = reads, writes

    # ATF's own steps reach the context through `getattr`, which no attribute walk can see, so
    # they say what they need instead. Declared beats inferred wherever both exist.
    for step in steps:
        generic = _generic(step.pattern)
        if generic is not None:
            step.needs = list(generic.needs)


def _step_defs(observed: dict[str, Any]) -> list[StepDef]:
    """Every step definition the collection pass saw, deduplicated and in picker order.

    Two modules may register the same wording; a picker that offers it twice is offering a choice
    that does not exist.
    """
    seen: dict[tuple[str, str], StepDef] = {}
    for entry in observed.get("steps") or []:
        keyword = str(entry.get("keyword", "")).lower()
        pattern = str(entry.get("pattern", ""))
        if not pattern or keyword not in _KEYWORDS:
            continue
        seen.setdefault(
            (keyword, pattern),
            StepDef(
                keyword=keyword,
                pattern=pattern,
                params=[str(name) for name in entry.get("params") or []],
                file=str(entry.get("file", "")),
                docstring=str(entry.get("docstring", "")),
            ),
        )
    return [seen[key] for key in sorted(seen)]


# ---- specs (static parse) -------------------------------------------------


def parse_specs(specs_dir: Path, nodes: dict[str, Node], resource_types: set[str]) -> list[Spec]:
    specs: list[Spec] = []
    if not specs_dir.is_dir():
        return specs
    for path in sorted(specs_dir.rglob("*.feature")):
        specs.extend(parse_feature(path, nodes, resource_types))
    return specs


def parse_feature(path: Path, nodes: dict[str, Node], resource_types: set[str]) -> list[Spec]:
    feature = ""
    narrative_lines: list[str] = []
    specs: list[Spec] = []
    current: Spec | None = None
    pending_tags: list[str] = []
    in_examples = False
    example_header: list[str] = []
    # Background steps run before every scenario in the feature, so each spec inherits them.
    background: list[Step] = []
    in_background = False

    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("@"):
            pending_tags = [tag.lstrip("@") for tag in line.split()]
            continue

        if line.startswith("Feature:"):
            feature = line[len("Feature:") :].strip()
            current, in_examples, in_background = None, False, False
            continue

        if line.startswith(("Scenario:", "Scenario Outline:", "Example:")):
            keyword, _, title = line.partition(":")
            current = Spec(
                id=f"{slug(feature)}::{slug(title)}",
                feature=feature,
                scenario=title.strip(),
                file=str(path),
                line=number,
                tags=pending_tags,
                skipped="skip" in pending_tags or "wip" in pending_tags,
            )
            current.steps.extend(Step(keyword=step.keyword, text=step.text) for step in background)
            specs.append(current)
            pending_tags, in_examples, example_header = [], False, []
            in_background = False
            continue

        if line.startswith(("Examples:", "Scenarios:")):
            in_examples = True
            example_header = []
            continue

        if line.startswith("Background:"):
            current, in_examples, in_background = None, False, True
            continue

        if in_examples and line.startswith("|") and current is not None:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if not example_header:
                example_header = cells
            else:
                current.examples.append(dict(zip(example_header, cells, strict=False)))
            continue

        keyword, _, text = line.partition(" ")
        if keyword in _STEP_KEYWORDS:
            if in_background:
                background.append(Step(keyword=keyword, text=text.strip()))
                continue
            if current is not None:
                current.steps.append(Step(keyword=keyword, text=text.strip()))
                continue

        if current is None and feature and not in_examples and not in_background:
            narrative_lines.append(line)

    narrative = " ".join(narrative_lines).strip()
    for spec in specs:
        spec.narrative = narrative
        _link_resources(spec, nodes, resource_types)  # after Examples, so `<placeholders>` expand
    return specs


def _link_resources(spec: Spec, nodes: dict[str, Node], resource_types: set[str]) -> None:
    for step in spec.steps:
        step.resources = _resources_in(step.text, spec, nodes, resource_types)
        for node_id in step.resources:
            if node_id not in spec.resources:
                spec.resources.append(node_id)


def _resources_in(text: str, spec: Spec, nodes: dict[str, Node], resource_types: set[str]) -> list[str]:
    """Node ids named by provisioning phrases. Words that aren't resource types are ignored."""
    found: list[str] = []
    for resource_type, name in PROVISION_RE.findall(text):
        if resource_type not in resource_types:
            continue
        for concrete in _example_values(name, spec):
            node = find_node(nodes, resource_type, concrete)
            if node is not None and node["id"] not in found:
                found.append(node["id"])
    return found


def _example_values(name: str, spec: Spec) -> list[str]:
    """`<who>` expands to every value the Examples table gives it; a literal stays itself."""
    if not (name.startswith("<") and name.endswith(">")):
        return [name]
    column = name[1:-1]
    values = [row[column] for row in spec.examples if column in row]
    return values or []


# ---- tests + fixtures (observed at collection time) ------------------------

# Discovery must never execute a test: the cockpit calls it on every page render, including for
# environments outside `mutable_envs`. Collection alone imports the suite and resolves each step
# to its definition, which is enough to learn the fixture closure — nothing is provisioned.
_OBSERVER = '''
import ast
import json
import os
import re

_PATH = os.environ["ATF_OBSERVE_OUT"]
_DATA = {"items": {}, "fixtures": {}, "steps": []}
_CAPTURE = re.compile(r"\\{([A-Za-z_][A-Za-z0-9_]*)(?::[^{}]*)?\\}")


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

    pytest-bdd spells it differently depending on version and parser class, so probe rather than
    assume: `name` on every `StepParser`, `pattern` where one is exposed, the compiled `regex` for
    a `parsers.re` step, and `str()` as the answer of last resort.
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
                found.append(
                    {
                        "keyword": context.type or "*",
                        "pattern": expression,
                        "params": _capture_names(context.parser, expression),
                        "file": getattr(getattr(function, "__code__", None), "co_filename", "") or "",
                        "docstring": " ".join((getattr(function, "__doc__", "") or "").split()),
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


def pytest_sessionfinish(session, exitstatus):
    # Read after collection has finished, so every steps module has been imported and registered.
    try:
        _DATA["steps"] = _step_definitions(session)
    except Exception:
        _DATA["steps"] = []
    with open(_PATH, "w") as handle:
        json.dump(_DATA, handle)
'''


def observe_pytest(root: Path, specs_dir: Path, env: str) -> tuple[dict[str, Any], list[str]]:
    """Collect the suite — never run it. See `_OBSERVER`."""
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        plugin_dir = Path(tmp)
        (plugin_dir / "atf_observer.py").write_text(_OBSERVER, encoding="utf-8")
        out = plugin_dir / "observed.json"

        environment = _child_env(root, env)
        environment["ATF_OBSERVE_OUT"] = str(out)
        environment["PYTHONPATH"] = os.pathsep.join(
            [str(plugin_dir), *filter(None, [environment.get("PYTHONPATH")])]
        )

        completed = _run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "atf_observer", str(specs_dir)],
            root,
            environment,
        )
        if completed is None:
            return {}, [f"discovery timed out after {_COLLECT_TIMEOUT}s"]
        if not out.exists():
            errors.append(_tail(completed.stdout + completed.stderr))
            return {}, errors
        if completed.returncode != 0:
            errors.append(_tail(completed.stdout + completed.stderr))
        return json.loads(out.read_text(encoding="utf-8")), errors


def _attach_tests(discovery: Discovery, observed: dict[str, Any], nodes: dict[str, Node]) -> None:
    by_scenario = {(spec.feature, spec.scenario): spec for spec in discovery.specs}

    for nodeid, entry in sorted(observed.get("items", {}).items()):
        feature = entry.get("feature", "")
        scenario = entry.get("scenario", "")
        spec = by_scenario.get((feature, scenario))
        name = str(entry.get("name", ""))
        params = name[name.index("[") + 1 : -1] if name.endswith("]") and "[" in name else ""

        observed_fixtures = list(observed.get("fixtures", {}).get(nodeid) or entry.get("fixtures") or [])
        # The generic step resolves a factory through `request.getfixturevalue(resource_type)`, so
        # the dependency is invisible to collection. The catalog link supplies it instead.
        if spec is not None:
            observed_fixtures += [
                nodes[node_id]["resource"] for node_id in spec.resources if node_id in nodes
            ]

        test = Test(
            id=slug(nodeid),
            nodeid=nodeid,
            name=name,
            params=params,
            file=str(entry.get("file", "")),
            covers=spec.id if spec else "",
            resources=list(spec.resources) if spec else [],
            fixtures=sorted({fixture for fixture in observed_fixtures if not fixture.startswith("_")}),
            skipped=bool(entry.get("skipped")) or (spec.skipped if spec else False),
        )
        if spec is not None and params:
            test.resources = _resources_for_row(spec, params)
        discovery.tests.append(test)
        if spec is not None:
            spec.test_ids.append(test.id)


def _resources_for_row(spec: Spec, params: str) -> list[str]:
    """An Examples row exercises only the resources its own values name."""
    values = set(params.split("-"))
    scoped = [node_id for node_id in spec.resources if node_id.split(".", 1)[-1] in values]
    fixed = [
        node_id
        for step in spec.steps
        for node_id in step.resources
        if not any(placeholder in step.text for placeholder in ("<", ">"))
    ]
    ordered = [node_id for node_id in spec.resources if node_id in set(scoped) | set(fixed)]
    return ordered or list(spec.resources)


def _fixtures(
    root: Path,
    env: str,
    observed: dict[str, Any],
    resource_types: set[str],
    errors: list[str],
    tests: list[Test],
) -> list[Fixture]:
    # Built from the finished tests, so generated factories attributed from the catalog appear here.
    used_by: dict[str, list[str]] = {}
    for test in tests:
        for name in test.fixtures:
            used_by.setdefault(name, []).append(test.nodeid)
    for nodeid, names in observed.get("fixtures", {}).items():
        for name in names:
            if nodeid not in used_by.setdefault(name, []):
                used_by[name].append(nodeid)

    described = _describe_fixtures(root, env, errors)
    fixtures: list[Fixture] = []
    for name in sorted(used_by):
        if name.startswith("_"):
            continue
        doc, scope = described.get(name, ("", "function"))
        fixtures.append(
            Fixture(
                name=name,
                doc=doc,
                scope=scope,
                used_by=sorted(used_by[name]),
                generated=name in resource_types,
            )
        )
    return fixtures


_FIXTURE_HEADER = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:\[(?P<scope>[a-z]+) scope\])?\s*--")


def _describe_fixtures(root: Path, env: str, errors: list[str]) -> dict[str, tuple[str, str]]:
    completed = _run(
        [sys.executable, "-m", "pytest", "--fixtures", "-v", "-q"],
        root,
        _child_env(root, env),
    )
    if completed is None or not completed.stdout:
        return {}

    described: dict[str, tuple[str, str]] = {}
    current: str | None = None
    doc_lines: list[str] = []
    scope = "function"

    def flush() -> None:
        if current:
            doc = " ".join(line for line in doc_lines if line).strip()
            described[current] = ("" if doc == "no docstring available" else doc, scope)

    for raw in completed.stdout.splitlines():
        header = _FIXTURE_HEADER.match(raw)
        if header:
            flush()
            current = header.group("name")
            scope = header.group("scope") or "function"
            doc_lines = []
        elif current and raw.startswith("    "):
            doc_lines.append(raw.strip())
        elif not raw.strip():
            continue
        elif current and not raw.startswith(" "):
            flush()
            current, doc_lines = None, []
    flush()
    return described


def _child_env(root: Path, env: str) -> dict[str, str]:
    environment = dict(os.environ)
    environment["ATF_ENV"] = env
    manifest = root / "atf.yaml"
    if manifest.is_file():
        environment["ATF_MANIFEST"] = str(manifest)
    return environment


def _run(command: list[str], cwd: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            timeout=_COLLECT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None


def _tail(text: str, limit: int = 800) -> str:
    stripped = text.strip()
    return stripped[-limit:] if len(stripped) > limit else stripped
