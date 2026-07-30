"""The suite, written out as markdown: features as living documentation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from ..model.text import plural
from ..run import verdict
from ..run.runner import TestResult
from ..spec.events import ERROR, FAILED
from .discovery import Question, Spec, Step, parse_questions, parse_specs

# Where the pages land when nobody says otherwise: inside the docs tree, in a directory of their
# own, so a generated page is never mixed in with a hand-written one.
DEFAULT_OUT = "docs/specs"

INDEX = "index.md"



@dataclass(frozen=True)
class Page:
    """One markdown file: where it goes under the output directory, and what is in it."""

    path: str
    title: str
    text: str


# ---- reading the suite ------------------------------------------------------


def read(specs_dir: Path) -> list[Spec]:
    """Every scenario under `specs_dir`, from a static parse of the feature files.

    No catalog is passed, so no resource is linked and nothing here can fail on one.
    """
    return parse_specs(Path(specs_dir))


def read_questions(specs_dir: Path) -> list[Question]:
    """What nobody could answer, from the same files.

    On the page for the same reason the scenarios are: a question is a thing the reader of this
    documentation may well be able to answer, and it will never reach them from a photograph of a
    workshop table.
    """
    return parse_questions(Path(specs_dir))


# ---- what the last runs said ------------------------------------------------


def _python_name(scenario: str) -> str:
    """The test function pytest-bdd generates for a scenario title.

    pytest-bdd is imported inside the function: it pulls in pytest, which every other command would
    otherwise pay for.
    """
    from pytest_bdd.scenario import get_python_name_generator

    return next(iter(get_python_name_generator(scenario)))


def _function_of(nodeid: str) -> str:
    """The test function a nodeid names, with any Examples row stripped off it."""
    return nodeid.rsplit("::", 1)[-1].split("[", 1)[0]


def results_for(spec: Spec, results: dict[str, TestResult]) -> list[TestResult]:
    """Everything the history holds about one scenario — one entry per Examples row."""
    wanted = _python_name(spec.scenario)
    return [result for nodeid, result in sorted(results.items()) if _function_of(nodeid) == wanted]


def state_of(spec: Spec, found: list[TestResult]) -> str:
    """One word for how a scenario stands, from the runs recorded for its rows."""
    return verdict.state_of(spec.skipped, (result.outcome for result in found))


def _counts(specs: list[Spec], results: dict[str, TestResult]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for spec in specs:
        state = state_of(spec, results_for(spec, results))
        tally[state] = tally.get(state, 0) + 1
    return tally


def _states_sentence(specs: list[Spec], results: dict[str, TestResult]) -> str:
    tally = _counts(specs, results)
    return ", ".join(f"{tally[state]} {state}" for state in verdict.ORDER if tally.get(state))


def _summary(specs: list[Spec], results: dict[str, TestResult], env: str) -> str:
    """How a set of scenarios stands, and where.

    The environment is in the sentence: a verdict with none on it is a rumour, the same scenario
    passing against dev and failing against staging.
    """
    size = plural(len(specs), "scenario")
    if not results:
        return f"{size}. Nothing has run against {env} yet."
    return f"{size} — {_states_sentence(specs, results)}, as of the runs recorded against {env}."


def tally(specs: list[Spec], results: dict[str, TestResult], env: str) -> str:
    """The one line `atf docs` prints when it is done, and the index page repeats."""
    features = plural(len({spec.file for spec in specs}), "feature")
    return f"{features}, {_summary(specs, results, env)}"


def _last_run_at(results: dict[str, TestResult]) -> float:
    return max((result.finished_at for result in results.values()), default=0.0)


# ---- rendering --------------------------------------------------------------


def render(
    specs: list[Spec],
    results: dict[str, TestResult],
    env: str,
    specs_dir: Path,
    questions: list[Question] | None = None,
) -> list[Page]:
    """Every page this suite produces: one per feature file, and an index over them."""
    grouped: dict[str, list[Spec]] = {}
    for spec in specs:
        grouped.setdefault(spec.file, []).append(spec)

    asked: dict[str, list[Question]] = {}
    for question in questions or []:
        asked.setdefault(question.file, []).append(question)

    pages = [
        _feature_page(path, members, results, env, specs_dir, asked.get(path, []))
        for path, members in sorted(grouped.items())
    ]
    return [_index_page(pages, grouped, results, env, questions or []), *pages]


def _page_path(feature_file: str, specs_dir: Path) -> str:
    """A feature's page, at the same place in the tree the feature sits at under `specs`.

    Nested, so two directories holding a feature of the same name produce two pages.
    """
    path = Path(feature_file)
    try:
        return path.resolve().relative_to(Path(specs_dir).resolve()).with_suffix(".md").as_posix()
    except (ValueError, OSError):
        return path.with_suffix(".md").name


def _feature_page(
    feature_file: str,
    specs: list[Spec],
    results: dict[str, TestResult],
    env: str,
    specs_dir: Path,
    questions: list[Question],
) -> Page:
    title = specs[0].feature or Path(feature_file).stem
    lines = [f"# {title}", ""]

    narrative = specs[0].narrative
    if narrative:
        lines += [narrative, ""]
    lines += [f"*{_summary(specs, results, env)}*", ""]
    lines += _question_lines([one for one in questions if not one.rule])

    rule = ""
    for spec in specs:
        if spec.rule and spec.rule != rule:
            lines += [f"## Rule: {spec.rule}", ""]
            lines += _question_lines([one for one in questions if one.rule == spec.rule])
        rule = spec.rule
        lines += _scenario_lines(spec, results)

    return Page(path=_page_path(feature_file, specs_dir), title=title, text="\n".join(lines).rstrip() + "\n")


def _question_lines(questions: list[Question]) -> list[str]:
    """What nobody could answer, under the rule it is about.

    On the page as well as in the file: the reader of a documentation site is often exactly the
    person who can answer one.
    """
    if not questions:
        return []
    return ["**Still unanswered:**", "", *[f"- {one.ask}" for one in questions], ""]


def _scenario_lines(spec: Spec, results: dict[str, TestResult]) -> list[str]:
    found = results_for(spec, results)
    lines = [f"### {spec.scenario}", "", f"*{_state_line(spec, found)}*", ""]
    lines += ["```gherkin", *_gherkin(spec.steps), "```", ""]

    if spec.examples:
        lines += ["Once for each row:", "", *_examples_table(spec.examples), ""]

    failure = _failure(found)
    if failure:
        lines += [*failure, ""]
    return lines


def _state_line(spec: Spec, found: list[TestResult]) -> str:
    """The verdict, with the tags the scenario carries — a `@wip` is why it says what it says."""
    state = state_of(spec, found)
    tags = " ".join(f"`@{tag}`" for tag in spec.tags)
    return f"{state} — {tags}" if tags else state


def _gherkin(steps: list[Step]) -> list[str]:
    """The steps back as Gherkin, tables included, which is the point of the whole command."""
    lines: list[str] = []
    for step in steps:
        lines.append(f"{step.keyword} {step.text}".rstrip())
        lines += [f"  | {' | '.join(row)} |" for row in step.table]
    return lines


def _examples_table(rows: list[dict[str, str]]) -> list[str]:
    """An Examples block as a markdown table, its header from the first row's keys."""
    header = list(rows[0])
    lines = [f"| {' | '.join(header)} |", f"|{'---|' * len(header)}"]
    lines += [f"| {' | '.join(row.get(column, '') for column in header)} |" for row in rows]
    return lines


def _failure(found: list[TestResult]) -> list[str]:
    """Why a failing scenario is failing: the step the run reached, and what it said there.

    A blockquote, which is the strongest markup a page rendered in four places can count on.
    """
    failed = next((result for result in found if result.outcome in {FAILED, ERROR}), None)
    if failed is None:
        return []
    step = failed.failed_step
    lines = ["> **This is not true right now.**"]
    if step is not None:
        lines.append(f"> It got as far as `{step.keyword} {step.text}`.")
    reason = _said(failed.detail)
    if reason:
        lines += [">", f"> `{reason}`"]
    return lines


def _said(detail: str) -> str:
    """The line of a failure a reader wants: what it said, not the file it stopped in."""
    lines = [line for line in detail.splitlines() if line.strip()]
    if not lines:
        return ""
    said = [line for line in lines if line.lstrip().startswith("E ")]
    if not said:
        return lines[-1].strip()
    # pytest marks the lines a failure *said* with a leading `E`. One character, dropped by index:
    # `lstrip` would also eat the E of a message starting "Error".
    return said[0].strip()[1:].strip()


def _index_page(
    pages: list[Page],
    grouped: dict[str, list[Spec]],
    results: dict[str, TestResult],
    env: str,
    questions: list[Question],
) -> Page:
    specs = [spec for members in grouped.values() for spec in members]
    lines = [
        "# Specifications",
        "",
        "Every feature in this suite, as it was written, with what the runs recorded so far say "
        "about it. Written by `atf docs`; edit the `.feature` files, not these pages.",
        "",
        f"*{tally(specs, results, env)}*",
        "",
    ]

    when = _last_run_at(results)
    if when:
        lines += [f"Newest run: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(when))}.", ""]
    if questions:
        lines += [f"{plural(len(questions), 'question')} nobody has answered yet.", ""]

    lines += ["| Feature | Scenarios | State |", "|---|---|---|"]
    for page, members in zip(pages, [grouped[path] for path in sorted(grouped)], strict=True):
        lines.append(f"| [{page.title}]({page.path}) | {len(members)} | {_states_sentence(members, results)} |")

    return Page(path=INDEX, title="Specifications", text="\n".join(lines).rstrip() + "\n")


# ---- writing ----------------------------------------------------------------


def write(pages: list[Page], out: Path) -> list[Path]:
    """Write every page under `out`, creating what it needs to. Nothing outside `out` is touched."""
    written: list[Path] = []
    for page in pages:
        target = Path(out) / page.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page.text, encoding="utf-8")
        written.append(target)
    return written
