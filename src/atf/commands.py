"""Every subcommand, and what each one answers."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import graph, reconcile, record, reports, scaffold
from .declare import declaration_of, name_of
from .environment import GroundError, build_ground
from .loader import Suite, SuiteError, load_suite
from .manifest import ManifestError, load
from .record import Verdict
from .reports import ReportError
from .spi import Did, State

OK, FAILED, NEVER_STARTED = 0, 1, 2

#: The four stable machine names `--json` puts on stderr for anything that exits `2`.
UNREACHABLE = "environment_unreachable"
INVALID = "suite_invalid"
IMMUTABLE = "environment_immutable"
USAGE = "usage"


@dataclass
class Answer:
    """What a subcommand produced: lines for a person, an object for a machine, and a code."""

    code: int = OK
    lines: list[str] | None = None
    data: Any = None
    error: str = ""
    error_code: str = ""

    def emit(self, as_json: bool, quiet: bool) -> int:
        if self.error:
            if as_json:
                print(json.dumps({"error": {"code": self.error_code or USAGE, "message": self.error}}), file=sys.stderr)
            else:
                print(self.error, file=sys.stderr)
            return self.code
        if as_json:
            print(json.dumps(self.data if self.data is not None else {}, indent=2))
        elif not quiet:
            for line in self.lines or []:
                print(line)
        return self.code


def fault(message: str, code_name: str = USAGE, code: int = NEVER_STARTED) -> Answer:
    return Answer(code=code, error=message, error_code=code_name)


def _suite(config: str | None) -> Suite:
    return load_suite(load(Path(config)) if config else None)


def _root(suite: Suite) -> Path:
    return suite.manifest.root


# --- status and make, as functions --------------------------------------------------------------
@dataclass(frozen=True)
class Report:
    """What one command did, in the shape a terminal, the editor and an agent all read."""

    env: str
    outcomes: list[reconcile.Reconciliation]
    code: int = OK
    error: str = ""

    @property
    def unreachable(self) -> list[reconcile.Reconciliation]:
        return [outcome for outcome in self.outcomes if outcome.state is State.UNREACHABLE]

    def lines(self) -> list[str]:
        """One line per resource, widest column first, for a terminal."""
        if self.error:
            return [self.error]
        width = max((len(outcome.name) for outcome in self.outcomes), default=0)
        out = []
        for outcome in self.outcomes:
            note = f"  ({outcome.why})" if outcome.why else ""
            changes = f"  changes: {', '.join(sorted(outcome.changes))}" if outcome.changes else ""
            out.append(f"{outcome.name:<{width}}  {outcome.state}  {outcome.did}{changes}{note}")
        return out


def _select(suite: Suite, names: list[str]) -> list[Any]:
    """The resources a command was pointed at, or all of them."""
    if not names:
        return list(suite.instances.values())
    return [suite.resource(name) for name in names]


def status(env: str = "", names: list[str] | None = None, *, manifest: Any = None) -> Report:
    """Where each resource stands in one environment. Changes nothing, and never exits `1`."""
    try:
        suite = load_suite(manifest)
        ground = build_ground(suite, env)
        outcomes = reconcile.status(ground, _select(suite, names or []))
    except Exception as exc:  # noqa: BLE001 - every failure here is "the run never started"
        return Report(env=env, outcomes=[], code=NEVER_STARTED, error=f"{type(exc).__name__}: {exc}")
    code = NEVER_STARTED if any(o.state is State.UNREACHABLE for o in outcomes) else OK
    return Report(env=ground.config.name, outcomes=outcomes, code=code)


def make(
    env: str = "",
    names: list[str] | None = None,
    *,
    dry_run: bool = False,
    manifest: Any = None,
) -> Report:
    """Make each named resource, and everything it needs, parents first."""
    try:
        suite = load_suite(manifest)
        ground = build_ground(suite, env)
        wanted = _select(suite, names or [])
        if not ground.mutable and not dry_run:
            # An environment that is not `mutable` refuses `make` before touching anything.
            return Report(
                env=ground.config.name,
                outcomes=[],
                code=NEVER_STARTED,
                error=(
                    f"the {ground.config.name} environment is not mutable, so nothing was made. "
                    f"Add `mutable: true` to it, or point at one that has it."
                ),
            )
        blocked = [problem for node in wanted for problem in graph.unmet(node) if not problem.has_factory]
        if blocked:
            return Report(
                env=ground.config.name,
                outcomes=[],
                code=NEVER_STARTED,
                error="this suite cannot be made:\n  - " + "\n  - ".join(str(problem) for problem in blocked),
            )
        outcomes = reconcile.provision(ground, wanted, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001
        return Report(env=env, outcomes=[], code=NEVER_STARTED, error=f"{type(exc).__name__}: {exc}")

    failed = [
        outcome
        for outcome in outcomes
        if outcome.state is State.UNREACHABLE
        or (outcome.state is State.ABSENT and outcome.did is Did.LEFT_ALONE and _was_required(outcome))
    ]
    return Report(env=ground.config.name, outcomes=outcomes, code=FAILED if failed else OK)


def _was_required(outcome: reconcile.Reconciliation) -> bool:
    """`require` is for something the environment owns, so its absence is a real failure."""
    return declaration_of(outcome.resource).when_absent == "require"


def graph_lines(suite: Suite) -> list[str]:
    """The graph as text, which is what `atf impact` and the editor draw from."""
    return [
        f"{name_of(node)}: {', '.join(name_of(parent) for parent in graph.parents(node)) or '-'}"
        for node in suite.order
    ]


# --- The subcommands ------------------------------------------------------------------------------


def do_init(*, env: str = "local", force: bool = False) -> Answer:
    """Scaffold ATF itself, and nothing else: a manifest, an empty `resources.py`, an empty `specs/`."""
    try:
        written = scaffold.init(Path.cwd(), env=env, force=force)
    except FileExistsError as exc:
        return Answer(code=FAILED, error=str(exc), error_code=USAGE)
    except OSError as exc:
        return fault(str(exc))
    return Answer(lines=[f"wrote {path}" for path in written], data={"written": [str(p) for p in written]})


def do_status(env: str = "", names: list[str] | None = None, *, config: str | None = None) -> Answer:
    """Where each resource stands. **Never gates** — `0` or `2`, and never `1`."""
    report = status(env, names or [], manifest=_manifest(config))
    if report.error:
        return fault(report.error, _classify(report.error))
    return Answer(
        code=report.code,
        lines=report.lines(),
        data={
            "environment": report.env,
            "resources": [
                {"name": o.name, "state": str(o.state), "would": str(o.did), "why": o.why} for o in report.outcomes
            ],
        },
    )


def do_make(
    env: str = "",
    names: list[str] | None = None,
    *,
    dry_run: bool = False,
    config: str | None = None,
) -> Answer:
    report = make(env, names or [], dry_run=dry_run, manifest=_manifest(config))
    if report.error:
        return fault(report.error, _classify(report.error))
    return Answer(
        code=report.code,
        lines=report.lines(),
        data={
            "environment": report.env,
            "resources": [
                {"name": o.name, "state": str(o.state), "did": str(o.did), "changes": sorted(o.changes), "why": o.why}
                for o in report.outcomes
            ],
        },
    )


def do_impact(
    name: str = "",
    *,
    tests_only: bool = False,
    resources_only: bool = False,
    depth: int = 0,
    config: str | None = None,
) -> Answer:
    """What breaks if a named resource does. Reads the graph, not history."""
    try:
        suite = _suite(config)
    except (ManifestError, SuiteError) as exc:
        return fault(str(exc), INVALID)

    everything = list(suite.instances.values())
    if not name:
        lines = [
            f"{name_of(node)}: {', '.join(name_of(p) for p in graph.parents(node)) or '-'}"
            for node in suite.order
        ]
        whole = {name_of(n): [name_of(p) for p in graph.parents(n)] for n in everything}
        return Answer(lines=lines, data={"graph": whole})

    if name not in suite.instances:
        return fault(f'no resource "{name}" in this suite', USAGE)

    target = suite.resource(name)
    affected = graph.dependents(target, everything)
    if depth:
        affected = _within(target, everything, depth)
    tests = _tests_reaching(suite, {name, *(name_of(node) for node in affected)})

    lines: list[str] = []
    if not tests_only:
        lines.append("resources")
        lines += [f"  {declaration_of(n).kind} {name_of(n)}" for n in affected] or ["  -"]
    if not resources_only:
        lines.append("tests")
        lines += [f"  {test}" for test in tests] or ["  -"]
    return Answer(
        lines=lines,
        data={
            "resource": name,
            **({} if tests_only else {"resources": [name_of(n) for n in affected]}),
            **({} if resources_only else {"tests": tests}),
        },
    )


def _within(target: Any, everything: list[Any], depth: int) -> list[Any]:
    """Dependents within so many steps of lineage. `--depth 1` is direct dependents only."""
    reached: list[Any] = []
    frontier = [target]
    for _ in range(depth):
        nearer = [
            node
            for node in everything
            if any(parent is step for step in frontier for parent in graph.parents(node))
            and not any(seen is node for seen in reached)
        ]
        if not nearer:
            break
        reached += nearer
        frontier = nearer
    return reached


def do_unused(*, strict: bool = False, kinds: list[str] | None = None, config: str | None = None) -> Answer:
    """What nothing asks for. `0` by default — an unused resource is often deliberate."""
    try:
        suite = _suite(config)
        from .plugin import Loaded  # noqa: PLC0415 - only this command needs the specs read

        vocabulary = Loaded(_root(suite)) if _root(suite).joinpath("atf.yaml").is_file() else None
    except (ManifestError, SuiteError, GroundError) as exc:
        return fault(str(exc), INVALID)

    kinds = kinds or ["resources", "phrases", "steps"]
    lines: list[str] = []
    data: dict[str, list[str]] = {}

    if "resources" in kinds:
        named = _resources_tests_name(vocabulary, suite)
        loose = [
            node
            for node in graph.unused(suite.instances.values())
            if name_of(node) not in named
        ]
        data["resources"] = [name_of(node) for node in loose]
        lines += [f"resource  {declaration_of(n).kind} {name_of(n):<20} nothing asks for it" for n in loose]

    if "phrases" in kinds and vocabulary is not None:
        said = {
            line.text
            for feature in vocabulary.features
            for scenario in feature.scenarios
            if not scenario.is_phrase
            for line in scenario.lines
        }
        loose_phrases = [
            pattern
            for pattern, phrase in vocabulary.phrases.items()
            if not any(phrase.match(sentence) for sentence in said)
        ]
        data["phrases"] = loose_phrases
        lines += [f'phrase    "{pattern}"   said by nothing' for pattern in loose_phrases]

    if "steps" in kinds and vocabulary is not None:
        from . import steps as step_registry  # noqa: PLC0415

        sentences = [
            (line.keyword, line.text)
            for feature in vocabulary.features
            for scenario in feature.scenarios
            for line in scenario.lines
        ]
        reached = {step_registry.matching(keyword, text) for keyword, text in sentences}
        loose_steps = [str(step) for step in step_registry.REGISTRY if step not in reached]
        data["steps"] = loose_steps
        lines += [f"step      {wording}   reached by nothing" for wording in loose_steps]

    anything = any(data.values())
    return Answer(code=FAILED if (strict and anything) else OK, lines=lines or ["nothing is unused"], data=data)


def _resources_tests_name(vocabulary: Any, suite: Suite) -> set[str]:
    """Resource names any test reaches, so `unused` means "no test and no resource"."""
    if vocabulary is None:
        return set()
    named: set[str] = set()
    for feature in vocabulary.features:
        for scenario in feature.scenarios:
            for line in scenario.lines:
                for word in line.text.replace('"', " ").split():
                    if word in suite.instances:
                        named.add(word)
    return named


def _relative(path: Any, root: Path) -> str:
    """A test identity is written from the suite root, so it reads the same everywhere."""
    try:
        return str(Path(path).relative_to(root))
    except (TypeError, ValueError):
        return str(path)


def _tests_reaching(suite: Suite, names: set[str]) -> list[str]:
    """Which tests name any of these resources. Read off the specs, before anything runs."""
    from .plugin import Loaded  # noqa: PLC0415

    try:
        vocabulary = Loaded(_root(suite))
    except Exception:  # noqa: BLE001 - impact answers about the graph even when the specs will not read
        return []
    out: list[str] = []
    for feature in vocabulary.features:
        for scenario in feature.scenarios:
            if scenario.is_phrase:
                continue
            words = {w for line in scenario.lines for w in line.text.replace('"', " ").split()}
            if words & names:
                out.append(f"{_relative(feature.path, _root(suite))}::{scenario.name}")
    return sorted(out)


def do_check(*, config: str | None = None) -> Answer:
    """Every registered check, over this suite. Exits `1` on findings, under `faults`."""
    from .registries import CHECKS  # noqa: PLC0415

    try:
        suite = _suite(config)
        from .plugin import Loaded  # noqa: PLC0415

        vocabulary = Loaded(_root(suite))
    except (ManifestError, SuiteError, GroundError) as exc:
        return fault(str(exc), INVALID)

    subject = _Checkable(suite=suite, vocabulary=vocabulary)
    faults: list[dict[str, str]] = []
    for one in CHECKS:
        for where, why in one.find(subject):
            faults.append({"check": one.description, "where": _name_of_subject(where), "why": why})

    lines = [f"{f['where']}: {f['why']}  ({f['check']})" for f in faults] or ["no faults"]
    return Answer(code=FAILED if faults else OK, lines=lines, data={"faults": faults})


@dataclass
class _Checkable:
    """What a check is handed: the declarations and the specs, already read."""

    suite: Suite
    vocabulary: Any

    @property
    def scenarios(self) -> list[Any]:
        return [
            scenario
            for feature in self.vocabulary.features
            for scenario in feature.scenarios
            if not scenario.is_phrase
        ]

    @property
    def resources(self) -> list[Any]:
        return list(self.suite.instances.values())

    @property
    def kinds(self) -> dict[str, type]:
        return dict(self.suite.kinds)


def _name_of_subject(where: Any) -> str:
    return getattr(where, "name", None) or str(where)


def do_docs(
    *, out: str = "./atf-docs", env: str = "", no_verdicts: bool = False, config: str | None = None
) -> Answer:
    """Render the specs as markdown, carrying the verdict history gives each scenario."""
    from . import rendering  # noqa: PLC0415
    from .plugin import Loaded  # noqa: PLC0415

    try:
        suite = _suite(config)
        vocabulary = Loaded(_root(suite))
    except (ManifestError, SuiteError, GroundError) as exc:
        return fault(str(exc), INVALID)

    environment = env or suite.manifest.default_env
    try:
        written = rendering.write(
            suite, vocabulary.features, Path(out), environment, with_verdicts=not no_verdicts
        )
    except OSError as exc:
        return fault(str(exc), USAGE)

    return Answer(
        lines=[rendering.summary(entry) for entry in written] or ["no scenarios to render"],
        data={
            "environment": environment,
            "pages": [
                {"path": str(path), "scenarios": total, "verdicts": counts}
                for path, total, counts in written
            ],
        },
    )


def do_import_run(env: str, file: str, format_: str = "ctrf", *, config: str | None = None) -> Answer:
    """Bring a run recorded elsewhere into this suite's history."""
    try:
        suite = _suite(config)
        imported = reports.read(Path(file), format_)
    except (ManifestError, SuiteError) as exc:
        return fault(str(exc), INVALID)
    except ReportError as exc:
        return fault(str(exc), USAGE)

    imported.id = record.new_id()
    imported.environment = env
    imported.source = "imported"
    imported.started = imported.started or record.now()
    imported.finished = imported.finished or imported.started
    path = record.save(_root(suite), imported)
    return Answer(
        lines=[f"imported {len(imported.outcomes)} outcomes into {env} as {imported.id}"],
        data={"id": imported.id, "environment": env, "path": str(path), "outcomes": len(imported.outcomes)},
    )


def do_history(env: str = "", *, config: str | None = None) -> Answer:
    """Past runs of one environment, newest last. Not in the specification; the editor reads it."""
    try:
        suite = _suite(config)
    except (ManifestError, SuiteError) as exc:
        return fault(str(exc), INVALID)
    wanted = env or suite.manifest.default_env
    runs = record.runs_for(_root(suite), wanted)
    flaky = record.flaky(_root(suite), wanted)
    return Answer(
        lines=[
            f"{run.id}  {run.started}  {run.source:<8} {str(run.verdict):<9} "
            f"{run.counts[record.Outcome.PASSED]} passed, {run.counts[record.Outcome.FAILED]} failed"
            for run in runs
        ]
        or ["no runs recorded"],
        data={
            "runs": [run.as_json() for run in runs],
            "flaky": sorted(flaky),
        },
    )


def _manifest(config: str | None) -> Any:
    return load(Path(config)) if config else None


def _classify(message: str) -> str:
    """Which of the four machine names a failure to start belongs to."""
    lowered = message.lower()
    if "unreachable" in lowered or "could not be reached" in lowered:
        return UNREACHABLE
    if "not mutable" in lowered or "immutable" in lowered:
        return IMMUTABLE
    if "manifest" in lowered or "no atf.yaml" in lowered:
        return USAGE
    return INVALID


def verdict_of(runs: list[record.Run]) -> Verdict:
    return record.verdict(outcome.outcome for run in runs for outcome in run.outcomes)
