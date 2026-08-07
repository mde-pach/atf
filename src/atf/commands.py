"""Every subcommand, and what each one answers."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import core, footprint, graph, reconcile, record, reports, scaffold
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

    def lines(self, only: list[reconcile.Reconciliation] | None = None) -> list[str]:
        """One line per resource, widest column first, for a terminal."""
        if self.error:
            return [self.error]
        shown = self.outcomes if only is None else only
        width = max((len(outcome.name) for outcome in shown), default=0)
        out = []
        for outcome in shown:
            note = f"  ({outcome.why})" if outcome.why else ""
            changes = f"  changes: {', '.join(sorted(outcome.changes))}" if outcome.changes else ""
            out.append(f"{outcome.name:<{width}}  {outcome.state}  {outcome.did}{changes}{note}")
        return out


def _select(suite: Suite, names: list[str]) -> list[Any]:
    """The resources a command was pointed at with the lineage they stand on, or all of them.

    A resource is never reported without what it needs: asking about `groceries` answers about
    `primary` as well.
    """
    if not names:
        return list(suite.instances.values())
    wanted: list[Any] = []
    for name in names:
        for node in graph.closure(suite.resource(name)):
            if not any(seen is node for seen in wanted):
                wanted.append(node)
    return wanted


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
        return Answer(code=FAILED, error=str(exc).replace(f"{Path.cwd()}/", ""), error_code=USAGE)
    except OSError as exc:
        return fault(str(exc))
    here = Path.cwd()
    return Answer(
        lines=[f"wrote {path.relative_to(here)}" for path in written],
        data={"written": [str(path) for path in written]},
    )


def do_status(
    env: str = "",
    names: list[str] | None = None,
    *,
    absent_only: bool = False,
    config: str | None = None,
) -> Answer:
    """Where each resource stands. **Never gates** — `0` or `2`, and never `1`."""
    report = status(env, names or [], manifest=_manifest(config))
    if report.error:
        return fault(report.error, _classify(report.error))
    shown = [o for o in report.outcomes if not absent_only or o.state is not State.PRESENT]
    return Answer(
        code=report.code,
        lines=report.lines(shown) or ["nothing is absent"],
        data={
            "environment": report.env,
            "resources": [
                {"name": o.name, "state": str(o.state), "would": str(o.did), "why": o.why} for o in shown
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


def do_drift(
    env: str = "", names: list[str] | None = None, *, strict: bool = False, config: str | None = None
) -> Answer:
    """What this environment holds that no longer matches its declaration.

    Reports by default and gates with `--strict`. Absence is not drift: a resource that is not there
    is `atf status`'s answer, and this one is about records that are there and have moved.
    """
    try:
        suite = _suite(config)
        ground = build_ground(suite, env)
        wanted = _select(suite, names or [])
    except (ManifestError, SuiteError, GroundError) as exc:
        return fault(str(exc), INVALID)
    except KeyError as exc:
        return fault(str(exc).strip("'"), USAGE)

    moved = [
        outcome
        for outcome in reconcile.status(ground, wanted)
        if outcome.state is State.PRESENT and outcome.changes
    ]
    lines: list[str] = []
    for outcome in moved:
        found = outcome.record or {}
        lines.append(f"{declaration_of(outcome.resource).kind} {outcome.name}")
        lines += [
            f"  {field}: {found.get(field)!r} declared {value!r}"
            for field, value in sorted(outcome.changes.items())
        ]
    return Answer(
        code=FAILED if (strict and moved) else OK,
        lines=lines or [f"{ground.config.name} matches every declaration"],
        data={
            "environment": ground.config.name,
            "drifted": [
                {
                    "name": outcome.name,
                    "kind": declaration_of(outcome.resource).kind,
                    "changes": {
                        field: {"found": (outcome.record or {}).get(field), "declared": value}
                        for field, value in outcome.changes.items()
                    },
                }
                for outcome in moved
            ],
        },
    )


def _changed_since(root: Path, revision: str) -> list[Path] | None:
    """Files this working tree has changed since a revision, or nothing where git cannot say."""
    try:
        top = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--show-toplevel"],  # noqa: S607
            cwd=root, capture_output=True, text=True, check=False, timeout=5,
        )
        listed = subprocess.run(  # noqa: S603
            ["git", "diff", "--name-only", revision],  # noqa: S607
            cwd=root, capture_output=True, text=True, check=False, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if top.returncode != 0 or listed.returncode != 0:
        return None
    where = Path(top.stdout.strip())
    return [where / line.strip() for line in listed.stdout.splitlines() if line.strip()]


def _declared_in(suite: Suite, changed: list[Path]) -> list[Any]:
    """Every resource whose kind is declared in one of these files."""
    import sys as system  # noqa: PLC0415 - the loaded modules are what says where a kind was written

    touched = {path.resolve() for path in changed}
    kinds = {
        kind
        for kind, cls in suite.kinds.items()
        if (module := system.modules.get(declaration_of(cls).module)) is not None
        and getattr(module, "__file__", None)
        and Path(str(module.__file__)).resolve() in touched
    }
    return [node for node in suite.instances.values() if declaration_of(node).kind in kinds]


def do_impact_since(revision: str, *, config: str | None = None) -> Answer:
    """What a change since this revision could have broken.

    A resources module that changed puts every kind it declares in scope, and lineage widens that
    the same way `--select +name` does. A feature file that changed names its own scenarios.
    """
    try:
        suite = _suite(config)
    except (ManifestError, SuiteError) as exc:
        return fault(str(exc), INVALID)

    root = _root(suite)
    changed = _changed_since(root, revision)
    if changed is None:
        return fault(f"git could not say what changed since {revision!r}", USAGE)

    everything = list(suite.instances.values())
    directly = _declared_in(suite, changed)
    affected = list(directly)
    for node in directly:
        for other in graph.dependents(node, everything):
            if not any(seen is other for seen in affected):
                affected.append(other)

    names = {name_of(node) for node in affected}
    tests = set(_tests_reaching(suite, names)) if names else set()
    for path in changed:
        if path.suffix == ".feature" and path.is_file():
            tests |= {one for one in _tests_in(suite, path, root)}

    lines = [f"changed since {revision}"]
    lines += [f"  {_relative(path, root)}" for path in changed] or ["  -"]
    lines.append("resources")
    lines += [f"  {declaration_of(n).kind} {name_of(n)}" for n in affected] or ["  -"]
    lines.append("tests")
    lines += [f"  {one}" for one in sorted(tests)] or ["  -"]
    return Answer(
        lines=lines,
        data={
            "since": revision,
            "changed": [_relative(path, root) for path in changed],
            "resources": sorted(names),
            "tests": sorted(tests),
        },
    )


def _tests_in(suite: Suite, path: Path, root: Path) -> list[str]:
    """The identities of the scenarios written in one feature file."""
    from . import feature as feature_reader  # noqa: PLC0415

    try:
        parsed = feature_reader.read(path)
    except Exception:  # noqa: BLE001 - a file that will not parse names no tests
        return []
    return [
        record.identity(path, scenario.name, root)
        for scenario in parsed.scenarios
        if not scenario.is_phrase
    ]


def do_impact(
    name: str = "",
    *,
    tests_only: bool = False,
    resources_only: bool = False,
    depth: int = 0,
    since: str = "",
    config: str | None = None,
) -> Answer:
    """What breaks if a named resource does. Reads the graph, not history."""
    if since:
        return do_impact_since(since, config=config)
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
            named |= footprint.of_scenario(suite, scenario, vocabulary.phrases).touches
    for _, _, asks in core._functions(suite):
        named |= footprint.of_function(suite, asks).touches
    return named


def _relative(path: Any, root: Path) -> str:
    """A test identity is written from the suite root, so it reads the same everywhere."""
    try:
        return str(Path(path).relative_to(root))
    except (TypeError, ValueError):
        return str(path)


def _tests_reaching(suite: Suite, names: set[str]) -> list[str]:
    """Which tests reach any of these resources. Read off the specs, before anything runs."""
    from .plugin import Loaded  # noqa: PLC0415

    root = _root(suite)
    try:
        vocabulary = Loaded(root)
    except Exception:  # noqa: BLE001 - impact answers about the graph even when the specs will not read
        return []
    out: list[str] = []
    for feature in vocabulary.features:
        for scenario in feature.scenarios:
            if scenario.is_phrase or feature.path is None:
                continue
            if footprint.of_scenario(suite, scenario, vocabulary.phrases).touches & names:
                out.append(record.identity(feature.path, scenario.name, root))
    for path, name, asks in core._functions(suite):
        if footprint.of_function(suite, asks).touches & names:
            out.append(record.identity(path, name, root))
    return sorted(out)


def do_check(*, strict: bool = False, config: str | None = None) -> Answer:
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

    if strict:
        loose = do_unused(config=config).data
        faults += [
            {"check": "nothing is unused", "where": one, "why": "nothing asks for it"}
            for what, names in loose.items()
            for one in names
        ]

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


def do_import_run(
    env: str,
    file: str,
    format_: str = "ctrf",
    *,
    label: str = "imported",
    revision: str = "",
    config: str | None = None,
) -> Answer:
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
    imported.label = label
    imported.revision = revision or imported.revision
    imported.started = imported.started or record.now()
    imported.finished = imported.finished or imported.started
    path = record.save(_root(suite), imported)
    return Answer(
        lines=[f"imported {len(imported.outcomes)} outcomes into {env} as {imported.id}"],
        data={"id": imported.id, "environment": env, "path": str(path), "outcomes": len(imported.outcomes)},
    )


def _suite_or_bare(config: str | None) -> Suite:
    """The suite, or one holding only its manifest where the resources will not read yet.

    `atf adopt` runs before there is anything to read: the file it writes is the one that would
    have to load.
    """
    manifest = load(Path(config)) if config else load()
    try:
        return load_suite(manifest)
    except SuiteError:
        from .declare import ADAPTERS  # noqa: PLC0415

        return Suite(manifest=manifest, adapters=dict(ADAPTERS))


def do_adopt(env: str = "", *, out: str = "", force: bool = False, config: str | None = None) -> Answer:
    """Write the declarations for what an environment already holds.

    Reads the environment and writes nothing but the file it is asked for. Without `--out` the
    source goes to stdout, so it can be looked at before it is kept.
    """
    from . import adopt as adopting  # noqa: PLC0415 - only this command reads a schema

    # Before the environment is read: a destination that cannot be written to is a refusal that
    # should cost nothing.
    destination = Path(out) if out else None
    if destination is not None and destination.exists() and not force and _declares_something(destination):
        return fault(f"{out} already declares resources; --force overwrites it", USAGE)

    try:
        suite = _suite_or_bare(config)
        ground = build_ground(suite, env)
        written, tables = adopting.from_ground(ground)
    except (ManifestError, SuiteError, GroundError) as exc:
        return fault(str(exc), INVALID)
    except adopting.AdoptError as exc:
        return fault(str(exc), USAGE)

    if destination is not None:
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(written, encoding="utf-8")
        except OSError as exc:
            return fault(str(exc), USAGE)
        nameless = [one["table"] for one in tables if not one["unique_by"]]
        lines = [f"wrote {out}: {len(tables)} kinds"]
        if nameless:
            lines.append(f"{len(nameless)} have no single unique column: {', '.join(sorted(nameless))}")
        return Answer(lines=lines, data={"wrote": out, "tables": tables})

    return Answer(lines=written.splitlines(), data={"source": written, "tables": tables})


def _declares_something(path: Path) -> bool:
    """Whether a file already holds a declaration, so overwriting it would lose one.

    Read as Python, so the commented example `atf init` scaffolds is not mistaken for one.
    """
    import ast  # noqa: PLC0415 - only this reads a file to see whether it declares anything

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return True
    return any(isinstance(node, ast.ClassDef) for node in ast.walk(tree))


def do_verify_adapter(name: str, env: str = "", *, config: str | None = None) -> Answer:
    """Put one resource's adapter through the contract, against a marked copy it then removes."""
    from . import conformance  # noqa: PLC0415 - only this command writes to prove a contract

    try:
        suite = _suite(config)
        ground = build_ground(suite, env)
        resource = suite.resource(name)
    except (ManifestError, SuiteError, GroundError) as exc:
        return fault(str(exc), INVALID)

    try:
        found = conformance.verify(ground, resource)
    except conformance.Unverifiable as exc:
        return fault(str(exc), USAGE)

    failed = [one for one in found if not one.held]
    declaration = declaration_of(resource)
    return Answer(
        code=FAILED if failed else OK,
        lines=[f"{declaration.system} — {declaration.kind} in {ground.config.name}", *(str(one) for one in found)],
        data={
            "system": declaration.system,
            "kind": declaration.kind,
            "environment": ground.config.name,
            "held": not failed,
            "findings": [{"what": one.what, "held": one.held, "why": one.why} for one in found],
        },
    )


def do_why_red(test: str, env: str = "", *, config: str | None = None) -> Answer:
    """When this test turned, and what the revision was on either side of the turn.

    Reads history and nothing else. A test with one outcome has not turned, and says so.
    """
    try:
        suite = _suite(config)
    except (ManifestError, SuiteError) as exc:
        return fault(str(exc), INVALID)

    root = _root(suite)
    environment = env or suite.manifest.default_env
    seen = [
        (run, outcome)
        for run in record.runs_for(root, environment)
        for outcome in run.outcomes
        if outcome.test == test
    ]
    if not seen:
        known = sorted({o.test for r in record.runs_for(root, environment) for o in r.outcomes})
        near = [one for one in known if test.lower() in one.lower()][:3]
        message = f"no test {test!r} in {environment}'s history"
        if near:
            message += "\n  did you mean:\n    " + "\n    ".join(near)
        return fault(message, USAGE)

    turns: list[tuple[Any, Any, Any, Any]] = []
    for (earlier, was), (later, now) in zip(seen, seen[1:], strict=False):
        if was.outcome is not now.outcome:
            turns.append((earlier, was, later, now))

    latest = seen[-1]
    lines = [f"{test}", f"  {latest[1].outcome} in {latest[0].id} ({latest[0].revision or 'no revision'})"]
    if not turns:
        lines.append(f"  {len(seen)} runs, and it has never changed its mind")
    for earlier, was, later, now in reversed(turns):
        lines.append(
            f"  {was.outcome} at {earlier.revision or earlier.id}, "
            f"{now.outcome} since {later.revision or later.id}"
        )
    if latest[1].failed_at is not None and latest[1].failed_at.step:
        lines.append(f"  {latest[1].failed_at.step}")
    return Answer(
        code=OK,
        lines=lines,
        data={
            "test": test,
            "environment": environment,
            "outcome": str(latest[1].outcome),
            "runs": len(seen),
            "turns": [
                {
                    "from": str(was.outcome),
                    "to": str(now.outcome),
                    "at": earlier.revision,
                    "since": later.revision,
                    "run": later.id,
                }
                for earlier, was, later, now in turns
            ],
        },
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
            f"{run.id}  {run.started}  {run.source:<8} {run.label or '-':<10} {str(run.verdict):<9} "
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
