"""Everything a suite says that can be read from its source, without running anything."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from ...model.catalog import Catalog
from ...spec.patterns import KEYWORDS, PROVISION_RE, literal_length, pattern_regex
from .model import Question, Spec, Step, StepDef, slug

_STEP_KEYWORDS = ("Given", "When", "Then", "And", "But", "*")

def matching_step(text: str, steps: list[StepDef]) -> StepDef | None:
    """The definition a step's wording resolves to, or None if this suite defines no such step.

    Matching happens here, not in pytest-bdd: the parsers live in the collection subprocess and what
    survives is the raw expression. An exact hit wins, then the expression read as a `{capture}`
    template, then as a regular expression, which is what `parsers.re` needs.

    More than one pattern can fit one line, a capture matching anything: `the {type} "{name}"` fits
    `the result field "plan" is "standard"` by reading the whole middle as a name. The one with the
    most *literal* text wins, which is the wording the author followed.
    """
    for step in steps:
        if step.pattern == text:
            return step
    for as_regex in (pattern_regex, str):
        fitting = []
        for step in steps:
            try:
                if re.fullmatch(as_regex(step.pattern), text):
                    fitting.append(step)
            except re.error:
                continue
        if fitting:
            return max(fitting, key=lambda step: literal_length(step.pattern))
    return None

# The decorators pytest-bdd registers a step with. `step` takes any keyword.
_STEP_DECORATORS = frozenset({"given", "when", "then", "step"})

# The fixture ATF's steps share. A function that does not take it cannot touch the context.
CONTEXT = "context"

def context_use(path: Path) -> dict[str, tuple[list[str], list[str]]]:
    """`{step wording: (what it reads from the context, what it writes)}` for one module.

    Read from source and never by running anything: discovery happens on every page render, and
    against read-only environments.

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

def attach_context_use(steps: list[StepDef]) -> None:
    """Read each module once, not once per step it declares."""
    from ...spec.steps import generic as _generic

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
            step.produces = list(generic.produces)
            step.needs_slot = generic.needs_slot
            step.takes_table = generic.takes_table

    _attach_phrase_use(steps)

def _attach_phrase_use(steps: list[StepDef]) -> None:
    """A phrase needs and produces whatever the steps it stands for do.

    Nothing can be read from a phrase's own source: it has none — it is a line of YAML that ATF
    turned into a step. So each of the steps it stands for is resolved against the same vocabulary
    the scenario would resolve it against, and the answers are unioned. Without this, a composer
    would offer a phrase standing for `the result field …` before anything had produced a result.
    """
    ordinary = [step for step in steps if not step.phrase]
    for phrase in (step for step in steps if step.phrase):
        needs: list[str] = []
        produces: list[str] = []
        for text in phrase.expands_to:
            stood_for = matching_step(text, ordinary)
            if stood_for is None:
                continue
            needs.extend(name for name in stood_for.needs if name not in needs)
            produces.extend(name for name in stood_for.produces if name not in produces)
            phrase.needs_slot = phrase.needs_slot or stood_for.needs_slot
        phrase.needs, phrase.produces = needs, produces

def step_defs(observed: dict[str, Any]) -> list[StepDef]:
    """Every step definition the collection pass saw, deduplicated and in picker order.

    Two modules may register the same wording; a picker that offers it twice is offering a choice
    that does not exist.
    """
    seen: dict[tuple[str, str], StepDef] = {}
    for entry in observed.get("steps") or []:
        keyword = str(entry.get("keyword", "")).lower()
        pattern = str(entry.get("pattern", ""))
        if not pattern or keyword not in KEYWORDS:
            continue
        seen.setdefault(
            (keyword, pattern),
            StepDef(
                keyword=keyword,
                pattern=pattern,
                params=[str(name) for name in entry.get("params") or []],
                file=str(entry.get("file", "")),
                docstring=str(entry.get("docstring", "")),
                expands_to=[str(text) for text in entry.get("expands_to") or []],
            ),
        )
    return [seen[key] for key in sorted(seen)]

def parse_specs(specs_dir: Path, catalog: Catalog | None = None) -> list[Spec]:
    specs: list[Spec] = []
    if not specs_dir.is_dir():
        return specs
    for path in sorted(specs_dir.rglob("*.feature")):
        specs.extend(parse_feature(path, catalog))
    return specs

# A question, written where Gherkin lets you write anything: a comment. `# ?` and not a bare comment,
# a feature file's comments being full of asides that are not questions.
_QUESTION_RE = re.compile(r"^\s*#\s*\?\s*(?P<ask>\S.*?)\s*$")

_RULE_RE = re.compile(r"^\s*Rule:\s*(?P<rule>.*)$")

_FEATURE_LINE_RE = re.compile(r"^\s*Feature:\s*(?P<feature>.*)$")

def parse_questions(specs_dir: Path) -> list[Question]:
    """Every `# ? …` line under `specs_dir`, with the feature and rule it sits under.

    A pass of its own, costing one regular expression per line: the questions and the scenarios are
    wanted in different places, and neither caller pays for the other.
    """
    found: list[Question] = []
    if not specs_dir.is_dir():
        return found
    for path in sorted(specs_dir.rglob("*.feature")):
        found.extend(questions_in(path))
    return found

def questions_in(path: Path) -> list[Question]:
    """The questions in one feature file, each attached to the rule above it."""
    feature, rule = "", ""
    found: list[Question] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return found

    for number, raw in enumerate(lines, start=1):
        if (asked := _QUESTION_RE.match(raw)) is not None:
            found.append(
                Question(
                    ask=asked.group("ask"),
                    feature=feature,
                    rule=rule,
                    file=str(path),
                    line=number,
                )
            )
            continue
        if (named := _FEATURE_LINE_RE.match(raw)) is not None:
            feature, rule = named.group("feature").strip(), ""
        elif (grouped := _RULE_RE.match(raw)) is not None:
            rule = grouped.group("rule").strip()
    return found

def parse_feature(path: Path, catalog: Catalog | None = None) -> list[Spec]:
    known = catalog if catalog is not None else Catalog()
    feature = ""
    rule = ""
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
            rule = ""
            continue

        if line.startswith("Rule:"):
            # A rule groups the scenarios under it until the next one. It carries no steps of its
            # own, so nothing else about parsing changes — which is the point of supporting it:
            # a feature gains the structure a discovery workshop already produced, for free.
            rule = line[len("Rule:") :].strip()
            current, in_examples, in_background = None, False, False
            continue

        if line.startswith(("Scenario:", "Scenario Outline:", "Example:")):
            keyword, _, title = line.partition(":")
            current = Spec(
                id=f"{slug(feature)}::{slug(title)}",
                feature=feature,
                scenario=title.strip(),
                rule=rule,
                file=str(path),
                line=number,
                tags=pending_tags,
                skipped="skip" in pending_tags or "wip" in pending_tags,
            )
            current.steps.extend(
                Step(keyword=step.keyword, text=step.text, table=[list(row) for row in step.table])
                for step in background
            )
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

        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if in_examples and current is not None:
                if not example_header:
                    example_header = cells
                else:
                    current.examples.append(dict(zip(example_header, cells, strict=False)))
                continue
            # Otherwise it is a table under the step above it, and belongs to that step. A row with
            # no step above it is a table nobody wrote a sentence for, and is dropped.
            above = background if in_background else (current.steps if current is not None else [])
            if above:
                above[-1].table.append(cells)
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
        _link_resources(spec, known)  # after Examples, so `<placeholders>` expand
    return specs

def _link_resources(spec: Spec, catalog: Catalog) -> None:
    for step in spec.steps:
        step.resources = _resources_in(step.text, spec, catalog)
        for node_id in step.resources:
            if node_id not in spec.resources:
                spec.resources.append(node_id)

def _resources_in(text: str, spec: Spec, catalog: Catalog) -> list[str]:
    """Node ids named by provisioning phrases. Words that aren't resource types are ignored."""
    found: list[str] = []
    for resource_type, name in PROVISION_RE.findall(text):
        if resource_type not in catalog.types:
            continue
        for concrete in _example_values(name, spec):
            node = catalog.find(resource_type, concrete)
            if node is not None and node.id not in found:
                found.append(node.id)
    return found

def _example_values(name: str, spec: Spec) -> list[str]:
    """`<who>` expands to every value the Examples table gives it; a literal stays itself."""
    if not (name.startswith("<") and name.endswith(">")):
        return [name]
    column = name[1:-1]
    values = [row[column] for row in spec.examples if column in row]
    return values or []
