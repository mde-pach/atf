"""The suite, written out as markdown: features as living documentation.

A spec is already the best description of what a system does — it is the only one that fails when
it stops being true. The problem has never been the writing, it is that the people who most need to
read it are the people least likely to open a `.feature` file in a repository. So `atf docs` puts
the features where documentation already lives: narrative, `Rule:` headings, scenarios as the lines
they were written as, and what the last run said about each one.

The pattern is not new — Pickles, Augurk and Serenity's living docs all do it. What they cannot do
is say whether the scenario currently *holds*, because they only ever see the file. ATF keeps a run
history on disk, so a page here can carry a verdict, and that is the whole difference between a
prettier feature file and documentation somebody trusts.

**Plain markdown into a directory, not a site generator plugin.** An mkdocs plugin would render on
every build and never go stale, and it would also tie this to mkdocs, run inside a docs build that
has no run history to read, and make the output impossible to review in a pull request. A directory
of CommonMark files is readable in mkdocs, in Docusaurus, in a GitHub blob view and in an editor's
preview pane — so nothing here uses an admonition, a snippet include or any other extension.

**It reads the feature files and the run store, and nothing else.** That is the same seam
[`atf lint`](lint.py) holds, and for the same reason: documentation you cannot build in a checkout
with no backend near it is documentation that stops being built. The alternative was full
[discovery](discovery.py) — collecting the suite with pytest, which is what the cockpit does — and
it would buy the resources each scenario touches at the price of needing an importable suite, every
`*_env` secret exported, and a working environment. The catalog is not read either: a page about
what the specs say should not fail because a resource type somewhere has a typo in it.

**A verdict is matched to a scenario by the test name pytest-bdd would generate for it.** Nothing
in the run history records which scenario a nodeid came from — it records nodeids, because that is
what pytest reports — and finding out properly means collecting the suite, which is the thing this
command is built not to do. pytest-bdd's own name generator is used rather than a rule
re-derived here, so the two can only disagree if pytest-bdd changes, and then they disagree in one
place. Two scenarios with the same title share a verdict; that is the known cost.

**What is known about a test, not what the newest run happened to include.** Running a subset is
normal, and reading only the last run would make every scenario it did not touch read "never run",
which is worse than slightly stale. Newest run wins, per test — the same rule the cockpit uses.

**A `Background:` is written into every scenario it runs before**, rather than hoisted to a heading
of its own. That is what actually happens when the scenario runs, and a reader who has to hold three
steps from further up the page in their head to understand this one is a reader the page has failed.

**Nothing is ever deleted.** A feature that was renamed leaves its old page behind, and the writer
removes it. A command that writes documentation is not a command that should be discovering, on its
own initiative, which of your files are surplus.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .discovery import Question, Spec, Step, parse_questions, parse_specs
from .run import verdict
from .run.events import ERROR, FAILED
from .runner import TestResult
from .text import plural

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

    The catalog is deliberately not passed, so no resource is linked and nothing here can fail on a
    catalog it was never asked about.
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

    Imported here rather than at module level: pytest-bdd pulls in pytest, and `atf status` should
    not pay for that because `atf docs` exists.
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

    The environment is in the sentence rather than left to the reader, because a verdict with no
    environment on it is a rumour: the same scenario passes against dev and fails against staging,
    and that is the normal case rather than the odd one.
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

    Flattening would read better — `cli.md` rather than `features/cli.md` — and would collide the
    first time two directories held a feature by the same name. A generated file that silently
    overwrites another generated file is not a trade worth a shorter path.
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

    On the page rather than only in the file, because the reader of a documentation site is often
    exactly the person who can answer one — and a question they never see is a question that becomes
    a bug instead.
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
    """An Examples block as a markdown table, because a reader is here to read, not to parse."""
    header = list(rows[0])
    lines = [f"| {' | '.join(header)} |", f"|{'---|' * len(header)}"]
    lines += [f"| {' | '.join(row.get(column, '') for column in header)} |" for row in rows]
    return lines


def _failure(found: list[TestResult]) -> list[str]:
    """Why a failing scenario is failing: the step the run reached, and what it said there.

    A blockquote rather than a warning admonition — see the module docstring: this file has to
    render in four places and only one of them knows what an admonition is.
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
    # pytest marks the lines a failure *said* with a leading `E`. One character, dropped by index
    # rather than by `lstrip`, which would also eat the E of a message starting "Error".
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
