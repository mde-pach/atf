"""`atf docs` — the specs as markdown, carrying the verdict each scenario last had."""

from __future__ import annotations

from pathlib import Path

from . import core, runs
from .feature import Feature
from .loader import Suite
from .runs import Verdict

TONE = {
    Verdict.PASSING: "passing",
    Verdict.FAILING: "failing",
    Verdict.SKIPPED: "skipped",
    Verdict.NEVER_RUN: "never run",
}


def render(feature: Feature, verdicts: dict[str, str], *, with_verdicts: bool = True) -> str:
    """One feature file as one markdown page."""
    lines = [f"# {feature.name or (feature.path.stem if feature.path else 'Feature')}", ""]
    if feature.background:
        lines += ["## Background", ""]
        lines += [f"- **{line.said}** {line.text}" for line in feature.background]
        lines.append("")

    for scenario in feature.scenarios:
        if scenario.is_phrase:
            continue
        verdict = verdicts.get(scenario.name, str(Verdict.NEVER_RUN))
        heading = f"## {scenario.name}"
        lines.append(f"{heading}  \n`{verdict}`" if with_verdicts else heading)
        if scenario.tags:
            lines.append("")
            lines.append(" ".join(f"`@{tag}`" for tag in scenario.tags))
        lines.append("")
        lines += [f"- **{line.said}** {line.text}" for line in scenario.lines]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def verdicts_for(suite: Suite, environment: str) -> dict[str, str]:
    """The last outcome each scenario had in this environment, folded into a verdict."""
    latest: dict[str, runs.Outcome] = {}
    for run in runs.runs_for(suite.manifest.root, environment):
        for outcome in run.outcomes:
            latest[outcome.test] = outcome.outcome

    out: dict[str, str] = {}
    for test, word in latest.items():
        name = test.split("::", 1)[-1]
        out[name] = str(runs.verdict([word]))
    return out


def write(
    suite: Suite,
    features: list[Feature],
    out: Path,
    environment: str,
    *,
    with_verdicts: bool = True,
) -> list[tuple[Path, int, dict[str, int]]]:
    """Write one page per feature, and report what each one carried."""
    out.mkdir(parents=True, exist_ok=True)
    verdicts = verdicts_for(suite, environment) if with_verdicts else {}
    written: list[tuple[Path, int, dict[str, int]]] = []

    for feature in features:
        scenarios = [one for one in feature.scenarios if not one.is_phrase]
        if not scenarios:
            continue
        name = (feature.path.stem if feature.path else "feature") + ".md"
        path = out / name
        path.write_text(render(feature, verdicts, with_verdicts=with_verdicts), encoding="utf-8")
        counts: dict[str, int] = {}
        for one in scenarios:
            word = verdicts.get(one.name, str(Verdict.NEVER_RUN))
            counts[word] = counts.get(word, 0) + 1
        written.append((path, len(scenarios), counts))
    return written


def summary(entry: tuple[Path, int, dict[str, int]]) -> str:
    """`wrote site/specs/lists.md      14 scenarios   13 passing   1 failing`."""
    path, total, counts = entry
    tail = "   ".join(f"{count} {word}" for word, count in sorted(counts.items()))
    return f"wrote {path}      {total} scenarios   {tail}"


def verdict_of_all(features: list[Feature], verdicts: dict[str, str]) -> Verdict:
    """The fold over every scenario rendered, for whoever wants one word about the suite."""
    return core.verdict_of(
        [
            core.TestEntry(id=one.name, label=one.name, form="scenario", tags=[], verdict=verdicts.get(one.name, ""))
            for feature in features
            for one in feature.scenarios
            if not one.is_phrase
        ]
    )
