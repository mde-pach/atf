"""Compose — assemble a scenario from the steps this suite really defines, then write it.

A raw editor with autocomplete assumes the reader already knows the model. This does not. `Given`
rows name resources and ATF provisions them, so they are a picker over the catalog rather than a
line to type; `When` and `Then` rows are the author's own vocabulary and are only ever offered from
the step definitions discovery found. Anyone who would rather type takes the text over in one click
and is held to exactly the same checks.

Two invariants govern the write. Every path is derived from `manifest.specs_dir`, never from the
form, so no wording can reach a file outside the suite. And the file is re-parsed after writing and
restored byte-for-byte if it no longer reads, because a `.feature` that will not parse costs the
whole suite its scenarios.
"""

from __future__ import annotations

import difflib
import os
import re
import secrets
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ...catalog import Node, find_node
from ...discovery import (
    CAPTURE_RE,
    GIVEN,
    PROVISION_RE,
    THEN,
    WHEN,
    Discovery,
    Spec,
    StepDef,
    fill,
    matching_step,
    parse_feature,
    slug,
)
from ...runner import ERROR, PASSED
from ...runner import run as run_tests
from ...steps import FIELD, NAME, TYPE, VALUE, generic
from ..view import cockpit as app
from ..view import current_env, field_choices, page, partial, plural, require_confirmation, require_mutable

router = APIRouter()

BUILD, TEXT = "build", "text"
KEYWORDS = (GIVEN, WHEN, THEN)

PURPOSE = "Name what a behaviour needs, then what it does and what must be true. Try it before you keep it."

DOCS_STEPS = "reference/specs-and-fixtures/"

# A feature name becomes a filename through `slug`, which cannot emit a separator. A name that
# carries one anyway is not a typo, so it is refused rather than quietly cleaned up.
_PATH_ISH = re.compile(r"[/\\]|\.\.")

# Lines that sit at the scenario's own indentation rather than a step's. `Examples:` is deliberately
# absent: it belongs with the steps, and its table rows deeper still.
_HEADING_RE = re.compile(r"^(Scenario|Scenario Outline|Example|Background):")


@dataclass
class Row:
    """One step under construction: a resource to name, or a step definition to instantiate."""

    index: int
    keyword: str
    resource_type: str = ""
    resource_name: str = ""
    pattern: str = ""
    values: dict[str, str] = field(default_factory=dict)
    definition: StepDef | None = None
    node_id: str = ""
    # What the context holds by the time this row runs, so the row can say whether its step fits.
    held: set[str] = field(default_factory=set)
    text: str = ""
    shown_keyword: str = ""
    problem: str = ""

    @property
    def given(self) -> bool:
        return self.keyword == GIVEN


@dataclass
class Trial:
    """What happened when a draft was run without being saved."""

    outcome: str = ""
    detail: str = ""
    step: str = ""
    duration: float = 0.0

    @property
    def passed(self) -> bool:
        return self.outcome == PASSED


@dataclass
class Draft:
    """A scenario being composed, and everything the page has to say about it."""

    env: str
    feature: str = ""
    feature_title: str = ""
    narrative: str = ""
    title: str = ""
    mode: str = BUILD
    text: str = ""
    rows: list[Row] = field(default_factory=list)
    block: str = ""
    path: Path | None = None
    before: str = ""
    after: str = ""
    problems: list[str] = field(default_factory=list)
    bad: dict[str, str] = field(default_factory=dict)
    diff: list[tuple[str, str]] = field(default_factory=list)
    written: bool = False
    next_steps: list[tuple[str, str, str]] = field(default_factory=list)
    spec_id: str = ""
    starting: bool = False
    trial: Trial | None = None
    bound: str = ""

    @property
    def where(self) -> str:
        return str(self.path) if self.path else ""


# ---- routes ----------------------------------------------------------------


@router.get("/compose")
def index(request: Request) -> Any:
    """The builder, empty or aimed at a feature that already exists."""
    env = current_env(request)
    fields = {
        "feature": request.query_params.get("feature", ""),
        "title": request.query_params.get("title", ""),
    }
    draft = _build(env, fields, rows=_starting_rows())
    return page(request, "compose.html", **_context(env, draft, validated=False))


@router.post("/compose/preview")
async def preview(request: Request) -> Any:
    """The live loop: re-read the form, re-resolve every step, re-render what will be written.

    Adding and removing rows come through here too, so the builder never holds state the server has
    not seen — a reload can therefore never disagree with the preview it was showing.
    """
    env = current_env(request)
    fields = await _fields(request)
    draft = _build(env, fields, rows=_rows(env, fields))
    return partial(request, "partials/compose_builder.html", **_context(env, draft))


@router.post("/compose/apply")
async def apply(request: Request) -> Any:
    """Write the scenario into its feature file, or leave that file exactly as it was.

    This edits source, not an environment, so `mutable_envs` has nothing to say about it: the same
    line of Gherkin would be written whichever environment the cockpit is pointed at.
    """
    env = current_env(request)
    fields = await _fields(request)
    require_confirmation(fields.get("confirm"))

    draft = _build(env, fields, rows=_rows(env, fields))
    if draft.problems:
        raise HTTPException(status_code=409, detail=f"not ready to write — {draft.problems[0]}")

    _write(draft)
    draft.bound = _bind(draft)
    app().invalidate(env)
    _after_writing(env, draft)
    return partial(request, "partials/compose_builder.html", **_context(env, draft))


@router.post("/compose/try")
async def try_it(request: Request) -> Any:
    """Run the draft without saving it.

    Composing a scenario and being told to go and run it somewhere else is the point at which the
    interface stops being one. This writes the draft to a scratch feature, runs that one scenario,
    reports what happened, and removes it again — so the answer arrives before the decision to keep
    it does.

    This one *is* gated by `mutable_envs`: unlike writing, running provisions.
    """
    env = current_env(request)
    require_mutable(env)
    fields = await _fields(request)
    require_confirmation(fields.get("confirm"))

    draft = _build(env, fields, rows=_rows(env, fields))
    if draft.problems:
        raise HTTPException(status_code=409, detail=f"not ready to run — {draft.problems[0]}")

    draft.trial = _try(env, draft)
    return partial(request, "partials/compose_builder.html", **_context(env, draft))


# ---- form state ------------------------------------------------------------


async def _fields(request: Request) -> dict[str, str]:
    form = await request.form()
    return {str(key): str(value) for key, value in form.multi_items() if isinstance(value, str)}


def _starting_rows() -> list[Row]:
    """One row per keyword: the shape of a scenario is the first thing the builder should teach."""
    return [Row(index=index, keyword=keyword) for index, keyword in enumerate(KEYWORDS)]


def offered_steps(env: str, feature: str) -> dict[str, list[StepDef]]:
    """The steps a scenario in `feature` can actually use, by keyword.

    Everything the composer does with steps goes through here — what it offers, and what it
    accepts. A step resolved from a wider set than it is offered from is a step someone can keep
    by switching feature after choosing it, and then find missing only when it runs.
    """
    cockpit = app()
    found = cockpit.discovery(env)
    binding = _binding_module(found, feature) if feature else None
    specs_dir = cockpit.manifest.specs_dir
    return {
        keyword: [step for step in found.steps_for(keyword) if reachable(step, binding, specs_dir)]
        for keyword in KEYWORDS
    }


def _rows(env: str, fields: dict[str, str]) -> list[Row]:
    found = offered_steps(env, fields.get("feature", "").strip())
    prefix = "kw_"
    indices = sorted(
        int(key[len(prefix) :]) for key in fields if key.startswith(prefix) and key[len(prefix) :].isdigit()
    )
    rows = [_row(index, fields, found) for index in indices if str(index) != fields.get("remove", "")]
    kept = [row for row in rows if row is not None]

    added = fields.get("add", "")
    if added in KEYWORDS:
        kept.append(Row(index=max((row.index for row in kept), default=-1) + 1, keyword=added))
    return kept


def _row(index: int, fields: dict[str, str], found: dict[str, list[StepDef]]) -> Row | None:
    keyword = fields.get(f"kw_{index}", "")
    if keyword not in KEYWORDS:
        return None
    row = Row(index=index, keyword=keyword)
    if row.given:
        row.resource_type = fields.get(f"rtype_{index}", "").strip()
        row.resource_name = fields.get(f"rname_{index}", "").strip()
        return row

    row.pattern = fields.get(f"pattern_{index}", "")
    row.definition = next((step for step in found[keyword] if step.pattern == row.pattern), None)
    if row.definition is not None:
        row.values = {name: fields.get(f"p_{index}_{name}", "").strip() for name in row.definition.params}
    return row


# ---- assembling the draft --------------------------------------------------


def _build(env: str, fields: dict[str, str], rows: list[Row]) -> Draft:
    cockpit = app()
    engine = cockpit.state(env).materializer
    found = cockpit.discovery(env)
    nodes, types = engine.nodes, set(engine.types)

    draft = Draft(
        env=env,
        feature=fields.get("feature", "").strip(),
        feature_title=fields.get("feature_title", "").strip(),
        narrative=fields.get("narrative", "").strip(),
        title=fields.get("title", "").strip(),
        mode=(fields.get("to_mode") or fields.get("mode") or BUILD).strip(),
        text=fields.get("text", ""),
        rows=rows,
    )
    if draft.mode not in (BUILD, TEXT):
        draft.mode = BUILD

    # Naming a feature and picking one are two different intents, so they are two controls rather
    # than an empty option in a list of real ones. Picking one always wins: the combo and the New
    # button post together, and choosing from the combo is the more recent decision.
    draft.starting = not draft.feature and (fields.get("new") == "1" or not _features(found))

    if draft.feature and draft.feature not in _features(found):
        known = ", ".join(_features(found)) or "none"
        raise HTTPException(status_code=404, detail=f"no feature named {draft.feature!r} here (this suite has {known})")

    _resolve(draft, nodes, found)
    draft.block = _gherkin(draft.title, draft.rows)
    # Entering text mode seeds the box from what the builder composed: taking the text over means
    # continuing from the same words, not starting again from nothing.
    if draft.mode == TEXT:
        draft.text = draft.text if draft.text.strip() else draft.block
        draft.block = _reindent(draft.text)

    draft.path, draft.before, draft.after = _target(draft, found)
    if draft.mode == TEXT:
        _check_text(draft, nodes, types, found)
    _check(draft, nodes, types, found)
    if draft.path is not None:
        draft.diff = _diff(draft.before, draft.after, str(draft.path))
    return draft


def _resolve(draft: Draft, nodes: dict[str, Node], found: Discovery) -> None:
    """Turn every row into the words it will write, and say plainly where it cannot yet."""
    for row in draft.rows:
        row.held = held_before(draft.rows, row.index)
        if row.given:
            _resolve_given(row, nodes)
        else:
            _resolve_step(row, found, nodes)

    # Only a row that produced a line counts as something for the next one to continue, so an
    # unfinished row in the middle can never leave an `And` with no keyword above it.
    previous = ""
    for row in draft.rows:
        row.shown_keyword = "And" if row.keyword == previous else row.keyword.capitalize()
        if row.text:
            previous = row.keyword


def _resolve_given(row: Row, nodes: dict[str, Node]) -> None:
    if not row.resource_type or not row.resource_name:
        row.problem = "pick a resource type and one of its instances"
        return
    row.text = f'the {row.resource_type} "{row.resource_name}"'
    node = find_node(nodes, row.resource_type, row.resource_name)
    if node is None:
        row.problem = f"the catalog declares no {row.resource_type} called {row.resource_name!r}"
        return
    row.node_id = node["id"]


def held_before(rows: list[Row], index: int) -> set[str]:
    """What the context holds by the time row `index` runs.

    A `Given` puts its record under the type's name; a `When` or `Then` puts whatever its own
    source says it writes. This is the whole of what a step can read, so it is the whole of what
    decides whether a step can be used here.
    """
    held: set[str] = set()
    for row in rows:
        if row.index == index:
            break
        if row.given and row.resource_type:
            held.add(row.resource_type)
        elif row.definition is not None:
            held.update(row.definition.produces)
    return held


def _resolve_step(row: Row, found: Discovery, nodes: dict[str, Node]) -> None:
    if not row.pattern:
        row.problem = f"choose the {row.keyword} step this scenario uses"
        return
    if row.definition is None:
        row.problem = (
            f"no {row.keyword} step this feature can reach is worded {row.pattern!r}"
        )
        row.text = row.pattern
        return

    row.text = fill(row.definition.pattern, row.values)
    missing = [name for name in row.definition.params if not row.values.get(name)]
    if missing:
        row.problem = f"give {'a value' if len(missing) == 1 else 'values'} for {', '.join(missing)}"
        return

    absent = [name for name in row.definition.needs if name not in row.held]
    if absent:
        row.problem = (
            f"nothing above this puts {' or '.join(absent)} on the context — "
            f"add a row that does, above it"
        )
        return

    # A step ATF defines names a catalog resource, so the composer can hold it to the catalog
    # exactly as it holds a Given row — rather than writing a line that only fails when it runs.
    if generic(row.definition.pattern) is not None and NAME in row.definition.params:
        resource_type, name = row.values.get(TYPE, ""), row.values.get(NAME, "")
        node = find_node(nodes, resource_type, name)
        if node is None:
            row.problem = f"the catalog declares no {resource_type} called {name!r}"
            return
        row.node_id = node["id"]


def _gherkin(title: str, rows: list[Row]) -> str:
    """The scenario block exactly as it will be written: two spaces in, its steps four.

    A repeated keyword becomes `And`, which is what someone writing this by hand would do and what
    the file has to look like for the diff to be worth reading. An untitled scenario is written
    untitled rather than given a placeholder name, so nothing invented here can end up on disk.
    """
    lines = [f"  Scenario: {title}".rstrip()]
    # A row with nothing chosen yet contributes no line: a bare `Given` is not something that would
    # ever be written, and the preview is only worth trusting if it is exactly what will be.
    lines += [f"    {row.shown_keyword} {row.text}" for row in rows if row.text]
    return "\n".join(lines) + "\n"


def _reindent(text: str) -> str:
    """Text the author typed, put back at the indentation a scenario sits at inside a feature.

    The parser does not care, but every human reader of the file does, and typing a scenario is no
    reason to end up with the one ragged block in the suite.
    """
    lines = [line.rstrip() for line in text.strip("\n").splitlines()]
    common = min((len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0)
    out: list[str] = []
    for line in lines:
        body = line[common:].lstrip()
        if not body:
            out.append("")
        elif _HEADING_RE.match(body) or body.startswith("@"):
            out.append("  " + body)
        elif body.startswith("|"):
            out.append("      " + body)
        else:
            out.append("    " + body)
    return "\n".join(out) + "\n"


# ---- where it goes ---------------------------------------------------------


def _features(found: Discovery) -> list[str]:
    return sorted({spec.feature for spec in found.specs if spec.feature})


def _feature_file(found: Discovery, feature: str) -> Path | None:
    return next((Path(spec.file) for spec in found.specs if spec.feature == feature and spec.file), None)


def _features_dir(found: Discovery) -> Path:
    """Where a new feature file belongs: beside the ones already there, else the specs root."""
    existing = sorted({Path(spec.file).parent for spec in found.specs if spec.file})
    return existing[0] if existing else app().manifest.specs_dir


def _target(draft: Draft, found: Discovery) -> tuple[Path | None, str, str]:
    """The file this scenario lands in, its bytes now, and its bytes afterwards.

    Appending keeps every existing byte and adds the block after a blank line; a new feature is a
    whole file. Either way the path comes from the manifest and a slug, never from the form.
    """
    if draft.feature:
        path = _feature_file(found, draft.feature)
        if path is None:
            return None, "", ""
        before = path.read_text(encoding="utf-8")
        if not before.strip():
            return _inside(path), before, draft.block
        return _inside(path), before, before.rstrip("\n") + "\n\n" + draft.block

    if not draft.feature_title:
        return None, "", ""
    if _PATH_ISH.search(draft.feature_title):
        raise HTTPException(
            status_code=409,
            detail="a feature name cannot contain a path — a scenario is only ever written under the specs directory",
        )
    head = f"Feature: {draft.feature_title}\n"
    if draft.narrative:
        head += f"  {draft.narrative}\n"
    return _inside(_features_dir(found) / f"{slug(draft.feature_title)}.feature"), "", head + "\n" + draft.block


def _inside(path: Path) -> Path:
    """Every write goes through here: a path outside `specs_dir` is refused, never clamped."""
    specs_dir = app().manifest.specs_dir.resolve()
    resolved = path.resolve()
    if specs_dir not in resolved.parents:
        raise HTTPException(status_code=409, detail=f"refusing to write outside {specs_dir}")
    return resolved


# ---- validation ------------------------------------------------------------


def _check(draft: Draft, nodes: dict[str, Node], types: set[str], found: Discovery) -> None:
    """Everything standing between this draft and a file that reads, said in words."""
    if not draft.title:
        draft.bad["title"] = "a scenario is named after the behaviour it describes"
        draft.problems.append("The scenario needs a title — it is the name the whole cockpit calls it by.")
    if draft.starting and not draft.feature_title:
        draft.bad["feature_title"] = "name the feature this scenario starts"
        draft.problems.append("Name the new feature, or add this scenario to one that already exists.")

    if draft.mode == BUILD:
        _check_rows(draft)

    if draft.path is None:
        return

    feature_name = draft.feature or draft.feature_title
    if draft.title and (feature_name, draft.title) in {(spec.feature, spec.scenario) for spec in found.specs}:
        draft.problems.append(f"{feature_name} already has a scenario called {draft.title!r}.")
    if draft.title:
        draft.spec_id = f"{slug(feature_name)}::{slug(draft.title)}"

    if not _added_specs(draft, nodes, types):
        draft.problems.append(
            "What would be written does not read back as a new scenario. A scenario line starts "
            "with `Scenario:` and its steps are indented under it."
        )


def _check_rows(draft: Draft) -> None:
    if not draft.rows:
        draft.problems.append("A scenario with no steps asserts nothing. Add a When and a Then.")
        return
    unresolved = [row for row in draft.rows if row.problem]
    if unresolved:
        draft.problems.append(
            f"{plural(len(unresolved), 'step')} {'does' if len(unresolved) == 1 else 'do'} not resolve yet — "
            + "; ".join(row.problem for row in unresolved)
            + "."
        )
    if not any(row.keyword == THEN for row in draft.rows):
        draft.problems.append("Nothing is asserted — a scenario needs at least one Then.")


def _check_text(draft: Draft, nodes: dict[str, Node], types: set[str], found: Discovery) -> None:
    """Text the author took over, held to the checks the builder enforced by construction.

    It is read with `parse_feature` — the reader every other page uses — so what the composer
    accepts and what the cockpit will show cannot come apart.
    """
    added = _added_specs(draft, nodes, types)
    if not added:
        return
    # The text is the authority on its own title once it is being edited directly, so the field
    # follows it rather than the other way round: the two must not be able to disagree.
    draft.title = added[0].scenario

    for spec in added:
        keyword = GIVEN
        for step in spec.steps:
            if step.keyword.lower() in KEYWORDS:
                keyword = step.keyword.lower()
            capture = CAPTURE_RE.search(step.text)
            if capture is not None:
                draft.problems.append(
                    f"{step.text!r} still has a placeholder in it — {capture.group(0)} is where a "
                    "value goes, not part of the wording."
                )
            elif keyword == GIVEN and PROVISION_RE.search(step.text):
                _check_named_resources(draft, step.text, spec, nodes, types)
            elif matching_step(step.text, found.steps_for(keyword)) is None:
                draft.problems.append(
                    f"No {keyword} step in this suite is worded {step.text!r} — pick an existing "
                    f"wording, or define it with @{keyword} in a steps/test_*.py module."
                )


def _check_named_resources(draft: Draft, text: str, spec: Spec, nodes: dict[str, Node], types: set[str]) -> None:
    """Every named resource has to be in the catalog. An outline is checked once per Examples row."""
    for resource_type, name in PROVISION_RE.findall(text):
        if resource_type not in types:
            draft.problems.append(f"{resource_type!r} is not a resource type in this catalog.")
            continue
        placeholder = name.startswith("<") and name.endswith(">")
        column = name[1:-1] if placeholder else ""
        values = [row[column] for row in spec.examples if column in row] if placeholder else [name]
        if placeholder and not values:
            draft.problems.append(f"No Examples column is called {column!r}, so <{column}> names nothing.")
        for value in values:
            if find_node(nodes, resource_type, value) is None:
                draft.problems.append(f"The catalog declares no {resource_type} called {value!r}.")


def _added_specs(draft: Draft, nodes: dict[str, Node], types: set[str]) -> list[Spec]:
    """The scenarios the prospective file adds — proof that what will be written parses."""
    if not draft.after.strip():
        return []
    was = {(spec.feature, spec.scenario) for spec in _parse(draft.before, nodes, types)}
    return [spec for spec in _parse(draft.after, nodes, types) if (spec.feature, spec.scenario) not in was]


def _parse(text: str, nodes: dict[str, Node], types: set[str]) -> list[Spec]:
    if not text.strip():
        return []
    with tempfile.TemporaryDirectory() as tmp:
        candidate = Path(tmp) / "candidate.feature"
        candidate.write_text(text, encoding="utf-8")
        return parse_feature(candidate, nodes, types)


# ---- writing ---------------------------------------------------------------


def _write(draft: Draft) -> None:
    """Write, re-read, and put the original bytes back if the result no longer parses.

    The only two acceptable outcomes are a file that reads and the file that was there before.
    """
    if draft.path is None:
        raise HTTPException(status_code=409, detail="there is nowhere to write this scenario yet")
    path = _inside(draft.path)

    engine = app().state(draft.env).materializer
    existed = path.exists()
    original = path.read_bytes() if existed else b""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(draft.after, encoding="utf-8")
    try:
        specs = parse_feature(path, engine.nodes, set(engine.types))
    except Exception:
        specs = []

    if not any(spec.scenario == draft.title for spec in specs):
        if existed:
            path.write_bytes(original)
        else:
            path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=409,
            detail=f"{path.name} would not have parsed with that scenario in it, so nothing was written",
        )
    draft.written = True


def _steps_dir(found: Discovery) -> Path:
    """Where the modules that bind features to pytest live — beside the ones already there."""
    existing = sorted({Path(test.file).parent for test in found.tests if test.file})
    return existing[0] if existing else app().manifest.specs_dir / "steps"


def _binds(specs_dir: Path, feature: Path) -> bool:
    """Whether some module already hands this feature to pytest."""
    for path in specs_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "scenarios(" in text and feature.name in text:
            return True
    return False


BINDING = '''"""Hands {name} to pytest. Written by the composer; add your own steps below."""

from pytest_bdd import scenarios

scenarios("{path}")
'''

# A `scenarios(...)` call on its own line — what binds a feature to pytest.
_SCENARIOS_CALL = re.compile(r"^[ \t]*scenarios\((?:[^()]|\([^()]*\))*\)[ \t]*$", re.MULTILINE)


def _binding_module(found: Discovery, feature: str) -> Path | None:
    """The module that hands this feature to pytest, if one does.

    It matters far beyond collection: pytest-bdd registers every step as a fixture in the module
    that declares it, so *which* module binds a feature decides which steps that feature can use.
    """
    for test in found.tests:
        spec = found.spec(test.covers) if test.covers else None
        if spec is not None and spec.feature == feature and test.file:
            return Path(test.file)
    return None


def _rebound(source: str, feature: Path, module_dir: Path) -> str:
    """A steps module, rewritten to bind `feature` instead of whatever it bound before.

    Copying the module rather than writing a bare one is what makes a trial faithful: a step is
    only visible to the module that declares it, so a scenario tried anywhere else would report
    steps missing that will resolve perfectly well once it is saved.
    """
    call = f'scenarios("{Path(os.path.relpath(feature, module_dir)).as_posix()}")'
    seen = False

    def swap(match: re.Match[str]) -> str:
        nonlocal seen
        if seen:
            return ""  # one feature per scratch module: the rest would collect twice
        seen = True
        return call

    rewritten = _SCENARIOS_CALL.sub(swap, source)
    return rewritten if seen else f"{rewritten}\n\n{call}\n"


def reachable(step: StepDef, module: Path | None, specs_dir: Path) -> bool:
    """Whether a step definition is visible from the module that will bind a feature.

    pytest's fixture rules, which is what step lookup really is: a step declared in a module is
    visible in that module, one declared in a `conftest.py` is visible below it, and one a plugin
    registered — every step ATF itself defines — is visible everywhere.
    """
    if not step.file:
        return True
    path = Path(step.file)
    try:
        path.relative_to(specs_dir)
    except ValueError:
        return True
    if path.name == "conftest.py":
        return module is None or path.parent in module.parents
    return module is not None and path == module


def _bind(draft: Draft) -> str:
    """Write the module that makes a feature collectable, unless something already does.

    A scenario composed here and then not collected is a scenario that does not exist as far as
    anything else is concerned, and being told to go and write a `.py` for it is exactly the seam
    this page exists to remove. Nothing is written when a module already binds the feature — which
    is the common case, because a feature only needs binding once.
    """
    cockpit = app()
    if draft.path is None:
        return ""
    specs_dir = cockpit.manifest.specs_dir
    if _binds(specs_dir, draft.path):
        return ""

    steps = _steps_dir(cockpit.discovery(draft.env))
    steps.mkdir(parents=True, exist_ok=True)
    module = _inside(steps / f"test_{slug(draft.path.stem)}.py")
    if module.exists():
        return ""

    relative = os.path.relpath(draft.path, module.parent)
    module.write_text(
        BINDING.format(name=draft.path.name, path=Path(relative).as_posix()), encoding="utf-8"
    )
    return str(module)


def _try(env: str, draft: Draft) -> Trial:
    """Run this scenario from a scratch file, then take the file away again."""
    cockpit = app()
    specs_dir = cockpit.manifest.specs_dir
    found = cockpit.discovery(env)

    name = f"atf_trying_{secrets.token_hex(4)}"
    binding = _binding_module(found, draft.feature) if draft.feature else None
    feature = _inside(_features_dir(found) / f"{name}.feature")
    module = _inside((binding.parent if binding else _steps_dir(found)) / f"test_{name}.py")
    heading = draft.feature or draft.feature_title or "Trying a scenario"

    try:
        feature.parent.mkdir(parents=True, exist_ok=True)
        module.parent.mkdir(parents=True, exist_ok=True)
        feature.write_text(f"Feature: {heading}\n\n{draft.block}", encoding="utf-8")
        # A copy of the module that will bind this scenario, so the trial sees the steps the real
        # run will. Bare, when the feature is new and no module binds it yet — which is also the
        # truth about what such a scenario would be able to reach.
        module.write_text(
            _rebound(binding.read_text(encoding="utf-8"), feature, module.parent)
            if binding
            else BINDING.format(
                name=feature.name, path=Path(os.path.relpath(feature, module.parent)).as_posix()
            ),
            encoding="utf-8",
        )
        summary = run_tests([str(module)], env, cockpit.manifest.root, specs_dir)
    finally:
        feature.unlink(missing_ok=True)
        module.unlink(missing_ok=True)

    result = next(iter(summary.results.values()), None)
    if result is None:
        return Trial(outcome=ERROR, detail=summary.output[-600:] or "the run produced no result")
    failed = result.failed_step
    return Trial(
        outcome=result.outcome,
        detail=(failed.error if failed else "") or result.detail,
        step=f"{failed.keyword} {failed.text}".strip() if failed else "",
        duration=result.duration,
    )


def _after_writing(env: str, draft: Draft) -> None:
    """The honest next step. A written scenario is not yet a running one.

    Two separate things stand between the two — a `scenarios(...)` binding, and a definition for any
    wording the suite has never seen. Saying "done" while either is missing would teach the model
    wrongly at precisely the moment it is being learnt.
    """
    found = app().discovery(env)
    spec = found.spec(draft.spec_id) if draft.spec_id else None
    if spec is None:
        draft.next_steps.append(
            ("Reload this page to see the new scenario — discovery has not caught up with it yet.", "", "")
        )
        return

    undefined = sorted({step.text for step in spec.steps if _undefined(step, spec, found)})
    if undefined:
        draft.next_steps.append(
            (
                "These steps have no definition yet, so pytest will report them missing: "
                + "; ".join(repr(text) for text in undefined)
                + ". Write one with @when or @then in a steps/test_*.py module.",
                "How steps are written",
                DOCS_STEPS,
            )
        )
    if not found.tests_for_spec(spec.id):
        draft.next_steps.append(
            (
                f"No test collects {spec.feature} yet, so pytest will not run this. Bind it with "
                f'scenarios("{_relative(spec.file)}") in a steps/test_*.py module and pytest collects '
                "one test per scenario.",
                "How scenarios become tests",
                DOCS_STEPS,
            )
        )


def _undefined(step: Any, spec: Spec, found: Discovery) -> bool:
    """Whether a written step has nothing behind it. A provisioning step always has."""
    keyword = step.keyword.lower()
    if keyword not in KEYWORDS:
        keyword = _effective_keyword(spec, step.text)
    if keyword == GIVEN and PROVISION_RE.search(step.text):
        return False
    return matching_step(step.text, found.steps_for(keyword)) is None


def _effective_keyword(spec: Spec, text: str) -> str:
    """What an `And` continues — a step's keyword in Gherkin is the last concrete one above it."""
    keyword = GIVEN
    for step in spec.steps:
        if step.keyword.lower() in KEYWORDS:
            keyword = step.keyword.lower()
        if step.text == text:
            return keyword
    return keyword


def _relative(file: str) -> str:
    """A feature path as a `scenarios(...)` call names it, from a `steps/` module beside it."""
    try:
        inside = Path(file).resolve().relative_to(app().manifest.specs_dir.resolve())
    except ValueError:
        return Path(file).name
    return "../" + inside.as_posix()


def _diff(before: str, after: str, label: str) -> list[tuple[str, str]]:
    """The proposed change, line by line, classed so it can be read before it is written."""
    lines: list[tuple[str, str]] = []
    for line in difflib.unified_diff(
        before.splitlines(), after.splitlines(), fromfile=label, tofile=label, lineterm="", n=2
    ):
        if line.startswith(("+++", "---")):
            lines.append(("file", line))
        elif line.startswith("@@"):
            lines.append(("meta", line))
        elif line.startswith("+"):
            lines.append(("add", line))
        elif line.startswith("-"):
            lines.append(("del", line))
        else:
            lines.append(("", line))
    return lines


# ---- context ---------------------------------------------------------------


def _context(env: str, draft: Draft, validated: bool = True) -> dict[str, Any]:
    cockpit = app()
    engine = cockpit.state(env).materializer
    found = cockpit.discovery(env)

    instances: dict[str, list[Node]] = {}
    for node in sorted(engine.nodes.values(), key=lambda item: item["name"]):
        instances.setdefault(node["resource"], []).append(node)

    status = cockpit.status(env)

    # Only the steps this scenario will actually be able to use. Offering one it cannot reach is
    # offering a scenario that composes cleanly and then fails to run for a reason nothing on the
    # page explains — pytest-bdd scopes a step to the module that declares it.
    binding = _binding_module(found, draft.feature) if draft.feature else None
    specs_dir = cockpit.manifest.specs_dir
    offered = offered_steps(env, draft.feature)

    return {
        "env": env,
        "title": "Compose a scenario",
        "purpose": PURPOSE,
        "draft": draft,
        "validated": validated,
        "features": _features(found),
        "types": sorted(engine.types),
        "instances": instances,
        "status": status,
        "offered": offered,
        "elsewhere": _elsewhere(found, offered, binding, specs_dir),
        "keywords": KEYWORDS,
        "specs_dir": cockpit.manifest.specs_dir,
        # Choices carry what is needed to make them: a list of names tells you nothing about which
        # name you want.
        "feature_options": _feature_options(found),
        "type_options": _type_options(engine, instances, status),
        "instance_options": lambda resource_type: _instance_options(instances.get(resource_type, []), status),
        # Per row, not per keyword: what a step can read depends on what the rows above it put
        # there, so the same picker two rows apart honestly offers different things.
        "step_options": lambda row: _step_options(
            [step for step in offered[row.keyword] if set(step.needs) <= row.held]
        ),
        "unusable": lambda row: [
            step for step in offered[row.keyword] if not set(step.needs) <= row.held
        ],
        # Only the steps ATF itself defines get a picker per parameter: they are the only ones
        # whose parameters ATF chose, so the only ones whose meaning it can know. A project's
        # step keeps a text box, because `{expected}` could be anything at all.
        "generic": generic,
        "field_options": lambda resource_type, name: _field_options(engine, status, resource_type, name),
        "current_value": lambda resource_type, name, field: _current_value(
            engine, status, resource_type, name, field
        ),
        "capture_kinds": (TYPE, NAME, FIELD, VALUE),
    }


def _elsewhere(
    found: Discovery, offered: dict[str, list[StepDef]], binding: Path | None, specs_dir: Path
) -> list[str]:
    """Modules holding steps this feature cannot use, so the reason can be said rather than felt.

    The fix is one a person has to choose between — put the scenario in the feature whose module
    already has the step, or move the step into a `conftest.py` where every feature can see it —
    so the interface names both and picks neither.
    """
    shown = {step.pattern for steps in offered.values() for step in steps}
    files = {
        Path(step.file).name
        for keyword in KEYWORDS
        for step in found.steps_for(keyword)
        if step.pattern not in shown and step.file and not reachable(step, binding, specs_dir)
    }
    return sorted(files)


def _feature_options(found: Discovery) -> list[dict[str, str]]:
    counts: dict[str, int] = {}
    for spec in found.specs:
        counts[spec.feature] = counts.get(spec.feature, 0) + 1
    return [
        {
            "value": name,
            "label": name,
            "meta": f"{counts.get(name, 0)} scenario" + ("" if counts.get(name) == 1 else "s"),
            "desc": "",
        }
        for name in sorted(counts)
    ]


def _type_options(engine: Any, instances: dict[str, list[Node]], status: dict[str, Any]) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for name in sorted(engine.types):
        members = instances.get(name, [])
        present = sum(1 for node in members if status.get(node["id"], {}).get("status") == "present")
        entry = engine.types[name]
        lifecycle = str(entry.get("lifecycle", "persistent"))
        mode = str(entry.get("mode", "create"))
        note = " · built fresh per run" if lifecycle == "ephemeral" else ""
        note += " · must already exist here" if mode == "reference" else ""
        options.append(
            {
                "value": name,
                "label": name,
                "meta": str(entry.get("system", "")),
                "desc": f"{len(members)} in the catalog, {present} present in this environment{note}",
            }
        )
    return options


def _instance_options(members: list[Node], status: dict[str, Any]) -> list[dict[str, str]]:
    """The resources of one type, each with where it stands and what it is for.

    Choosing between `primary` and `secondary` is impossible from the names alone, which is exactly
    what `represents` was written to answer.
    """
    return [
        {
            "value": node["name"],
            "label": node["name"],
            "meta": str(status.get(node["id"], {}).get("status", "unknown")),
            "desc": node["represents"] or node["id"],
        }
        for node in members
    ]


def _step_options(steps: list[StepDef]) -> list[dict[str, str]]:
    """Every step of one keyword, the ones needing no code first.

    Order is the whole point here. An author looking for "check this field" will take the first
    plausible thing they see, and if that is a step the project had to write, they conclude that
    assertions are something you write. They are not, for anything in the catalog.
    """
    options: list[dict[str, str]] = []
    for step in steps:
        mine = generic(step.pattern) is None
        options.append(
            {
                "value": step.pattern,
                "label": step.pattern,
                "meta": Path(step.file).name if step.file else "",
                "desc": step.docstring,
                "group": "This suite's own" if mine else "Ready to use",
                "rank": "1" if mine else "0",
            }
        )
    return sorted(options, key=lambda option: (option["rank"], option["label"]))


def _field_options(
    engine: Any, status: dict[str, Any], resource_type: str, name: str
) -> list[dict[str, str]]:
    """The fields of one resource, each carrying what it holds right now.

    Choosing a field from a list of bare names is guessing. Choosing `done` while the interface
    says it is currently `false` is writing an assertion with the answer in front of you.
    """
    node = find_node(engine.nodes, resource_type, name)
    if node is None:
        return []
    return [
        {"value": choice.name, "label": choice.name, "meta": choice.current, "desc": choice.source}
        for choice in field_choices(node, status.get(node["id"]))
    ]


def _current_value(engine: Any, status: dict[str, Any], resource_type: str, name: str, field: str) -> str:
    node = find_node(engine.nodes, resource_type, name)
    if node is None:
        return ""
    return next(
        (choice.current for choice in field_choices(node, status.get(node["id"])) if choice.name == field),
        "",
    )
