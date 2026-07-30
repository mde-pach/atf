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

**What can be said here is not decided in this file.** Which steps a feature can reach, what a claim
means, what a resource's fields currently hold and what those choices compose into all live in
[`introspect.py`](../../introspect.py), which knows nothing about the web. This router turns a form
into those questions and the answers into a page — and everything below the form is shared with
anything else that wants to compose a scenario without opening an editor.
"""

from __future__ import annotations

import difflib
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ...catalog import Catalog
from ...compare import MARKERS
from ...discovery import Discovery, Spec, StepDef, matching_step, parse_feature, slug
from ...introspect import (
    KEYWORDS,
    NODE_SUBJECT,
    Outside,
    Row,
    Surface,
    Trial,
    action_options,
    aspect_options,
    comparison_options,
    current_value,
    elsewhere,
    feature_options,
    field_options,
    gherkin,
    held_fields,
    instance_options,
    instances_by_type,
    make_row,
    resolve,
    resource_options,
    row_problems,
    step_options,
    subject_options,
    table_fields,
    try_scenario,
    type_options,
    usable,
)
from ...introspect import binding_module as _binding_module
from ...introspect import features as _features
from ...introspect import features_dir as _features_dir
from ...introspect import inside as _inside_of
from ...introspect import offered_steps as _offered_steps
from ...patterns import CAPTURE_RE, GIVEN, PROVISION_RE
from ...steps import ACTION, FIELD, NAME, TYPE, VALUE, comparison, generic
from ..view import cockpit as app
from ..view import current_env, page, partial, require_confirmation, require_mutable

router = APIRouter()

BUILD, TEXT = "build", "text"

PURPOSE = "Name what a behaviour needs, then what it does and what must be true. Try it before you keep it."

DOCS_STEPS = "reference/specs-and-fixtures/"

# A feature name becomes a filename through `slug`, which cannot emit a separator. A name that
# carries one anyway is not a typo, so it is refused rather than quietly cleaned up.
_PATH_ISH = re.compile(r"[/\\]|\.\.")

# Lines that sit at the scenario's own indentation rather than a step's. `Examples:` is deliberately
# absent: it belongs with the steps, and its table rows deeper still.
_HEADING_RE = re.compile(r"^(Scenario|Scenario Outline|Example|Background):")


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

    @property
    def where(self) -> str:
        return str(self.path) if self.path else ""


def surface(env: str) -> Surface:
    """This environment as everything that decides what can be said about it.

    Assembled here rather than cached because each part of it is already cached one layer down: the
    cockpit hands back the same materializer, discovery and status until something invalidates them.
    """
    cockpit = app()
    return Surface(
        env=env,
        root=cockpit.manifest.root,
        specs_dir=cockpit.manifest.specs_dir,
        engine=cockpit.state(env).materializer,
        found=cockpit.discovery.of(env),
        status=cockpit.status.of(env),
    )


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
    app().invalidate(env)
    _after_writing(env, draft)
    return partial(request, "partials/compose_builder.html", **_context(env, draft))


@router.post("/compose/try")
async def try_it(request: Request) -> Any:
    """Run the draft without saving it.

    This one *is* gated by `mutable_envs`: unlike writing, running provisions.
    """
    env = current_env(request)
    require_mutable(env)
    fields = await _fields(request)
    require_confirmation(fields.get("confirm"))

    draft = _build(env, fields, rows=_rows(env, fields))
    if draft.problems:
        raise HTTPException(status_code=409, detail=f"not ready to run — {draft.problems[0]}")

    try:
        draft.trial = try_scenario(
            surface(env), draft.block, draft.feature, draft.feature or draft.feature_title
        )
    except Outside as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return partial(request, "partials/compose_builder.html", **_context(env, draft))


# ---- form state ------------------------------------------------------------


async def _fields(request: Request) -> dict[str, str]:
    form = await request.form()
    return {str(key): str(value) for key, value in form.multi_items() if isinstance(value, str)}


def _starting_rows() -> list[Row]:
    """One row per keyword: the shape of a scenario is the first thing the builder should teach."""
    return [Row(index=index, keyword=keyword) for index, keyword in enumerate(KEYWORDS)]


def offered_steps(env: str, feature: str) -> dict[str, list[StepDef]]:
    """The steps a scenario in `feature` can actually use, by keyword."""
    return _offered_steps(surface(env), feature)


def _rows(env: str, fields: dict[str, str]) -> list[Row]:
    """The form, read back as the rows it describes.

    The one thing this file knows that the introspection layer does not is how a row is spelled in
    a form. Everything after that — what the choices mean, whether the step exists, what it writes —
    is the same question however it arrived.
    """
    found = offered_steps(env, fields.get("feature", "").strip())
    prefix = "kw_"
    indices = sorted(
        int(key[len(prefix) :]) for key in fields if key.startswith(prefix) and key[len(prefix) :].isdigit()
    )
    catalog = app().state(env).materializer.catalog
    kept = [
        make_row(index, keyword, _chosen(index, fields), found, catalog)
        for index in indices
        if str(index) != fields.get("remove", "")
        if (keyword := fields.get(f"kw_{index}", "")) in KEYWORDS
    ]

    added = fields.get("add", "")
    if added in KEYWORDS:
        kept.append(Row(index=max((row.index for row in kept), default=-1) + 1, keyword=added))
    return kept


def _chosen(index: int, fields: dict[str, str]) -> dict[str, Any]:
    """One row's choices, lifted out of the form's flat namespace."""
    prefix = f"p_{index}_"
    return {
        "resource_type": fields.get(f"rtype_{index}", ""),
        "resource_name": fields.get(f"rname_{index}", ""),
        "subject": fields.get(f"subject_{index}", ""),
        "aspect": fields.get(f"aspect_{index}", ""),
        "compare": fields.get(f"compare_{index}", ""),
        "target": fields.get(f"target_{index}", ""),
        "pattern": fields.get(f"pattern_{index}", ""),
        "params": {key[len(prefix) :]: value for key, value in fields.items() if key.startswith(prefix)},
        "table": _table(index, fields),
    }


def _table(index: int, fields: dict[str, str]) -> list[list[str]]:
    """The rows somebody filled in under a step that takes a table.

    A row with neither a field nor a value is one the page is offering and nobody has used, so it
    is dropped rather than written — the preview has to be exactly what lands on disk. A row with
    one of the two is kept, so that a half-filled row is reported rather than silently discarded.
    """
    prefix = f"tf_{index}_"
    numbers = sorted(
        int(key[len(prefix) :]) for key in fields if key.startswith(prefix) and key[len(prefix) :].isdigit()
    )
    rows = [[fields.get(f"tf_{index}_{n}", "").strip(), fields.get(f"tv_{index}_{n}", "").strip()] for n in numbers]
    return [row for row in rows if row[0] or row[1]]


# ---- assembling the draft --------------------------------------------------


def _build(env: str, fields: dict[str, str], rows: list[Row]) -> Draft:
    where = surface(env)
    found = where.found
    catalog = where.catalog

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

    resolve(draft.rows, where)
    draft.block = gherkin(draft.title, draft.rows)
    # Entering text mode seeds the box from what the builder composed: taking the text over means
    # continuing from the same words, not starting again from nothing.
    if draft.mode == TEXT:
        draft.text = draft.text if draft.text.strip() else draft.block
        draft.block = _reindent(draft.text)

    draft.path, draft.before, draft.after = _target(draft, where)
    if draft.mode == TEXT:
        _check_text(draft, catalog, found)
    _check(draft, catalog, found)
    if draft.path is not None:
        draft.diff = _diff(draft.before, draft.after, str(draft.path))
    return draft


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


def _feature_file(found: Discovery, feature: str) -> Path | None:
    return next((Path(spec.file) for spec in found.specs if spec.feature == feature and spec.file), None)


def _target(draft: Draft, where: Surface) -> tuple[Path | None, str, str]:
    """The file this scenario lands in, its bytes now, and its bytes afterwards.

    Appending keeps every existing byte and adds the block after a blank line; a new feature is a
    whole file. Either way the path comes from the manifest and a slug, never from the form.
    """
    if draft.feature:
        path = _feature_file(where.found, draft.feature)
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
    return _inside(_features_dir(where) / f"{slug(draft.feature_title)}.feature"), "", head + "\n" + draft.block


def _inside(path: Path) -> Path:
    """Every write goes through here: a path outside `specs_dir` is refused, never clamped."""
    try:
        return _inside_of(path, app().manifest.specs_dir)
    except Outside as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


# ---- validation ------------------------------------------------------------


def _check(draft: Draft, catalog: Catalog, found: Discovery) -> None:
    """Everything standing between this draft and a file that reads, said in words."""
    if not draft.title:
        draft.bad["title"] = "a scenario is named after the behaviour it describes"
        draft.problems.append("The scenario needs a title — it is the name the whole cockpit calls it by.")
    if draft.starting and not draft.feature_title:
        draft.bad["feature_title"] = "name the feature this scenario starts"
        draft.problems.append("Name the new feature, or add this scenario to one that already exists.")

    if draft.mode == BUILD:
        draft.problems.extend(row_problems(draft.rows))

    if draft.path is None:
        return

    feature_name = draft.feature or draft.feature_title
    if draft.title and (feature_name, draft.title) in {(spec.feature, spec.scenario) for spec in found.specs}:
        draft.problems.append(f"{feature_name} already has a scenario called {draft.title!r}.")
    if draft.title:
        draft.spec_id = f"{slug(feature_name)}::{slug(draft.title)}"

    if not _added_specs(draft, catalog):
        draft.problems.append(
            "What would be written does not read back as a new scenario. A scenario line starts "
            "with `Scenario:` and its steps are indented under it."
        )


def _check_text(draft: Draft, catalog: Catalog, found: Discovery) -> None:
    """Text the author took over, held to the checks the builder enforced by construction.

    It is read with `parse_feature` — the reader every other page uses — so what the composer
    accepts and what the cockpit will show cannot come apart.
    """
    added = _added_specs(draft, catalog)
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
                _check_named_resources(draft, step.text, spec, catalog)
            elif matching_step(step.text, found.steps_for(keyword)) is None:
                draft.problems.append(
                    f"No {keyword} step in this suite is worded {step.text!r} — pick an existing "
                    f"wording, or define it with @{keyword} in a steps/test_*.py module."
                )


def _check_named_resources(draft: Draft, text: str, spec: Spec, catalog: Catalog) -> None:
    """Every named resource has to be in the catalog. An outline is checked once per Examples row."""
    for resource_type, name in PROVISION_RE.findall(text):
        if resource_type not in catalog.types:
            draft.problems.append(f"{resource_type!r} is not a resource type in this catalog.")
            continue
        placeholder = name.startswith("<") and name.endswith(">")
        column = name[1:-1] if placeholder else ""
        values = [row[column] for row in spec.examples if column in row] if placeholder else [name]
        if placeholder and not values:
            draft.problems.append(f"No Examples column is called {column!r}, so <{column}> names nothing.")
        for value in values:
            if catalog.find(resource_type, value) is None:
                draft.problems.append(f"The catalog declares no {resource_type} called {value!r}.")


def _added_specs(draft: Draft, catalog: Catalog) -> list[Spec]:
    """The scenarios the prospective file adds — proof that what will be written parses."""
    if not draft.after.strip():
        return []
    was = {(spec.feature, spec.scenario) for spec in _parse(draft.before, catalog)}
    return [spec for spec in _parse(draft.after, catalog) if (spec.feature, spec.scenario) not in was]


def _parse(text: str, catalog: Catalog) -> list[Spec]:
    if not text.strip():
        return []
    with tempfile.TemporaryDirectory() as tmp:
        candidate = Path(tmp) / "candidate.feature"
        candidate.write_text(text, encoding="utf-8")
        return parse_feature(candidate, catalog)


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
        specs = parse_feature(path, engine.catalog)
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


def _after_writing(env: str, draft: Draft) -> None:
    """The honest next step. A written scenario is not yet a running one.

    Two separate things stand between the two — a `scenarios(...)` binding, and a definition for any
    wording the suite has never seen. Saying "done" while either is missing would teach the model
    wrongly at precisely the moment it is being learnt.
    """
    found = app().discovery.of(env)
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
    where = surface(env)
    instances = instances_by_type(where)

    # Only the steps this scenario will actually be able to use. Offering one it cannot reach is
    # offering a scenario that composes cleanly and then fails to run for a reason nothing on the
    # page explains — pytest-bdd scopes a step to the module that declares it.
    binding = _binding_module(where.found, draft.feature) if draft.feature else None
    offered = _offered_steps(where, draft.feature)

    return {
        "env": env,
        "title": "Compose a scenario",
        "purpose": PURPOSE,
        "draft": draft,
        "validated": validated,
        "features": _features(where.found),
        "types": where.catalog.resource_types,
        "instances": instances,
        "status": where.status,
        "offered": offered,
        "elsewhere": elsewhere(where.found, offered, binding, where.specs_dir),
        "keywords": KEYWORDS,
        "specs_dir": where.specs_dir,
        # Choices carry what is needed to make them: a list of names tells you nothing about which
        # name you want.
        "feature_options": feature_options(where.found),
        "type_options": type_options(where),
        "instance_options": lambda resource_type: instance_options(
            instances.get(resource_type, []), where.status
        ),
        # Per row, not per keyword: what a step can read depends on what the rows above it put
        # there, so the same picker two rows apart honestly offers different things.
        # A step carrying a table is left out of both pickers: the builder has no way to write the
        # table under it, and offering a line it cannot finish is worse than not offering it. Those
        # are written by hand, or in text mode, which is held to exactly the same checks.
        "step_options": lambda row: step_options(
            [step for step in offered[row.keyword] if usable(step, row)]
        ),
        # A Then said as a claim: what it is about, what of it, how, and against what.
        "subject_options": lambda row: subject_options(
            where, [step for step in offered[row.keyword] if usable(step, row)], row
        ),
        # What a table's rows can be about: the fields this row's resource is known to have, with
        # what each holds right now. The composer already reads these for the single-field claim —
        # a whole-shape claim is the same question asked about several fields at once, and the
        # tedium it replaces is exactly why it was worth teaching the builder to write one.
        "table_fields": lambda row: table_fields(where, row),
        # What a cell may say instead of a value, offered rather than remembered.
        "markers": MARKERS,
        "aspect_options": lambda row: aspect_options(where, row.subject.removeprefix(NODE_SUBJECT)),
        "held_fields": lambda: held_fields(cockpit.results.of(env)),
        "comparison_options": comparison_options,
        "resource_options": resource_options(where),
        "claim": comparison,
        "unusable": lambda row: [step for step in offered[row.keyword] if not usable(step, row)],
        # Only the steps ATF itself defines get a picker per parameter: they are the only ones
        # whose parameters ATF chose, so the only ones whose meaning it can know. A project's
        # step keeps a text box, because `{expected}` could be anything at all.
        "generic": generic,
        # What can be *done* to a resource of this type. Data in the catalog, so it is enumerable —
        # which is the same property that made assertions composable, and the reason `actions:` is
        # declared rather than written as a step.
        "action_options": lambda resource_type: action_options(where, resource_type),
        "field_options": lambda resource_type, name: field_options(where, resource_type, name),
        "current_value": lambda resource_type, name, of_field: current_value(
            where, resource_type, name, of_field
        ),
        "capture_kinds": (TYPE, NAME, FIELD, VALUE, ACTION),
    }
