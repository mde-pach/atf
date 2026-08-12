"""The `atf` entry point: six commands, `atf run`, and the three exit codes."""

from __future__ import annotations

import contextlib
import io
import os
import random
import subprocess
import sys
import tempfile
from concurrent import futures
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
import pytest

from . import __version__, commands, naming, reports, runs
from .commands import FAILED, INVALID, NEVER_STARTED, OK, USAGE, Answer, fault
from .loader import SuiteError, load_suite
from .manifest import ManifestError, load
from .reports import ReportError
from .runner import Collected, Selection, build_run
from .runs import Outcome

#: The contract every system holds, written in ATF's own language and shipped with it.
CONTRACT = Path(__file__).parent / "contract.feature"


@dataclass
class Options:
    """The flags every subcommand accepts, carried on Click's context."""

    as_json: bool = False
    config: str | None = None
    quiet: bool = False


def globals_too(command: Any) -> Any:
    """Let the global flags be written after the subcommand as well as before it."""
    for option in (
        click.option("--json", "as_json_after", is_flag=True, help="emit the answer as JSON"),
        click.option("--config", "config_after", metavar="PATH", default=None, help="the manifest to read"),
        click.option("--quiet", "-q", "quiet_after", is_flag=True, help="suppress progress"),
    ):
        command = option(command)
    return command


def _adopt(context: click.Context, flags: dict[str, Any]) -> None:
    """Fold the after-the-subcommand spellings into the options this run is using."""
    options: Options = context.obj
    for name in ("as_json", "config", "quiet"):
        later = flags.pop(f"{name}_after", None)
        if later:
            setattr(options, name, later)


def _guarded(context: click.Context, work: Any) -> None:
    """Run a subcommand, emit its answer, and exit with its code."""
    options: Options = context.obj
    try:
        answer = work()
    except KeyboardInterrupt:
        print("interrupted; nothing was recorded", file=sys.stderr)
        context.exit(NEVER_STARTED)
    except Exception as exc:  # noqa: BLE001 - the exit code is the point
        answer = fault(f"{type(exc).__name__}: {exc}", INVALID)
    context.exit(answer.emit(as_json=options.as_json, quiet=options.quiet))


@click.group(context_settings={"help_option_names": ["-h", "--help"]}, invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True, help="emit the answer as JSON, errors as JSON on stderr")
@click.option("--config", metavar="PATH", help="the manifest to read (default ./atf.yaml)")
@click.option("--quiet", "-q", is_flag=True, help="suppress progress; the exit code and files remain")
@click.version_option(__version__, "--version", message="atf %(version)s")
@click.pass_context
def cli(context: click.Context, as_json: bool, config: str | None, quiet: bool) -> None:
    """Declared things, and the tests that need them."""
    context.obj = Options(as_json=as_json, config=config, quiet=quiet)
    if context.invoked_subcommand is None:
        click.echo(context.get_help())


@cli.command()
@globals_too
@click.option("--env", default="local", show_default=True, help="name of the first environment written")
@click.option("--force", is_flag=True, help="overwrite an existing atf.yaml")
@click.option("--no-run", is_flag=True, help="scaffold, and do not run the scenario it writes")
@click.pass_context
def init(context: click.Context, **flags: Any) -> None:
    """Start me off: look around, declare what is there, write one scenario, run it green."""
    _adopt(context, flags)
    _guarded(
        context,
        lambda: commands.do_init(env=flags["env"], force=flags["force"], run_it=not flags["no_run"]),
    )


@cli.command()
@globals_too
@click.argument("env", required=False, default="")
@click.argument("names", nargs=-1)
@click.option("--apply", is_flag=True, help="make what is missing, and run nothing")
@click.option("--lives", "lives_too", is_flag=True, help="also say how long each thing lives, and why")
@click.pass_context
def plan(context: click.Context, **flags: Any) -> None:
    """Is this suite sound, and what will happen? Works against a dead environment."""
    _adopt(context, flags)
    _guarded(
        context,
        lambda: commands.do_plan(
            flags["env"],
            list(flags["names"]),
            apply=flags["apply"],
            lives_too=flags["lives_too"],
            config=context.obj.config,
        ),
    )


@cli.command()
@globals_too
@click.argument("pointed_at", required=False, default="", metavar="[THING]")
@click.option("--env", default="", help="whose standing and history to read")
@click.pass_context
def explain(context: click.Context, **flags: Any) -> None:
    """Tell me everything about this: a thing, a kind, a system, a scenario, a phrase, a file."""
    _adopt(context, flags)
    _guarded(
        context,
        lambda: commands.do_explain(flags["pointed_at"], flags["env"], config=context.obj.config),
    )


@cli.command()
@globals_too
@click.argument("scenario", required=False, default="")
@click.option("--env", default="", help="which environment to arrange in")
@click.option("--say", multiple=True, help="a line to type at the prompt; repeatable, then it exits")
@click.pass_context
def enter(context: click.Context, **flags: Any) -> None:
    """Put me inside this failure. With no argument: the thing that just broke."""
    _adopt(context, flags)
    _guarded(
        context,
        lambda: commands.do_enter(
            flags["scenario"], flags["env"], config=context.obj.config, typed=list(flags["say"])
        ),
    )


@cli.command()
@globals_too
@click.option("--env", default="", help="environment to open on; the first one unless given")
@click.option("--port", default=8765, type=int, show_default=True, help="which port")
@click.option("--mcp", is_flag=True, help="serve the same operations to an agent instead")
@click.option("--write", default="", metavar="DIRECTORY", help="write the spec out instead of serving it")
@click.pass_context
def edit(context: click.Context, **flags: Any) -> None:
    """Let me look around: the suite, its graph, its spec and its own vocabulary."""
    _adopt(context, flags)
    if flags["write"]:
        _guarded(
            context,
            lambda: commands.do_render(out=flags["write"], env=flags["env"], config=context.obj.config),
        )
        return

    config = context.obj.config
    manifest = Path(config) if config else None
    if flags["mcp"]:
        from .agent import serve as serve_agent
        from .editor import Editor

        try:
            serve_agent(Editor(manifest, flags["env"]))
        except RuntimeError as exc:
            message = str(exc)
            _guarded(context, lambda: fault(message, USAGE))
        return
    _guarded(context, lambda: commands.do_edit(flags["env"], flags["port"], config=config))


# --- The one subcommand that executes anything ---------------------------------------------------


@cli.command()
@globals_too
@click.option("--env", default="", help="environment to run against; the first one unless given")
@click.option(
    "--select",
    default="",
    metavar="THING",
    help="only scenarios reaching this thing, kind, system, phrase or file",
)
@click.option("--tag", multiple=True, help="only scenarios carrying this tag; repeatable, OR")
@click.option("--failed", is_flag=True, help="only tests whose last outcome here was failed")
@click.option("--accept", is_flag=True, help="draft the claims for scenarios that promise none")
@click.option("--contract", is_flag=True, help="also run the contract every system holds")
@click.option("--report", multiple=True, metavar="FORMAT:PATH", help="write a report; repeatable")
@click.option("--import", "import_", default="", metavar="PATH", help="bring a run recorded elsewhere into history")
@click.option("--format", "format_", default="ctrf", show_default=True, help="what --import reads")
@click.option("--no-make", is_flag=True, help="do not make missing things")
@click.option("--dry-run", is_flag=True, help="print the selected identities and exit 0")
@click.option("-k", "keyword", default="", help="only tests whose identity matches this expression")
@click.option("--jobs", default="auto", show_default=True, metavar="N|auto", help="how much runs at once")
@click.option("--shard", default="", metavar="I/N", help="run one slice of the laid-out run")
@click.option("--seed", type=int, default=None, help="run the selected tests in this order")
@click.option("--shuffle", is_flag=True, help="run them in an order nothing chose, and record the seed")
@click.option("--explain", "explaining", is_flag=True, help="say what can run beside what, and run nothing")
@click.option("--tests-from", default="", metavar="PATH", help="confine this run to the identities in this file")
@click.option("--no-record", is_flag=True, help="run and report, and leave history alone")
@click.option("--namespace", default="", help="the token resolution builds recognition values from")
@click.argument("tests", nargs=-1, metavar="[TEST]...")
@click.pass_context
def run(context: click.Context, **flags: Any) -> None:
    """Run the tests, and record a run.

    Two scenarios that share nothing permanent cannot interfere, so the run is laid out
    concurrently with no flag: `--jobs` is `auto` unless it is given a number.
    """
    _adopt(context, flags)
    _guarded(context, lambda: do_run(context.obj, **flags))


def _locate(manifest: Any, identity: str) -> str:
    """Where a named test lives. A test identity is `<file>::<title>`."""
    where, separator, title = identity.partition("::")
    for root in (manifest.root, manifest.specs):
        candidate = root / where
        if candidate.is_file():
            return f"{candidate}{separator}{title}"
    return str(manifest.specs / identity)


def _selected_tests(options: Options, manifest: Any, select: str, env: str) -> set[str] | None:
    """The scenario titles `--select` narrows a run to, read off the sentences.

    It takes what `atf explain` takes: a thing, a kind, a system, a phrase, a scenario or a file.
    """
    if not select:
        return None
    from . import explain as explaining

    reading = commands.read(options.config, env, needs_ground=False)
    subject = explaining.about(
        reading.suite,
        reading.features,
        reading.phrases,
        reading.ground,
        manifest.root,
        env or manifest.default_env,
        select,
    )
    return set(subject.tests)


def do_run(options: Options, **flags: Any) -> Answer:
    """Run tests and record a run.

    Exits `0` when no test failed — **including a selection that legitimately matched nothing**.
    Exits `1` when at least one did. Exits `2` when the run never started, in which case nothing was
    recorded.
    """
    try:
        manifest = load(Path(options.config)) if options.config else load()
        load_suite(manifest)
    except ManifestError as exc:
        return fault(str(exc), USAGE)
    except SuiteError as exc:
        return fault(str(exc), INVALID)

    environment = flags["env"] or manifest.default_env
    if environment not in manifest.environments:
        known = ", ".join(manifest.environments) or "none"
        return fault(f"no environment {environment!r} in this manifest (known: {known})", USAGE)

    if flags.get("import_"):
        return _import_run(manifest, environment, flags)

    selection = Selection(tags=list(flags["tag"]), failed=flags["failed"], keyword=flags["keyword"])
    try:
        selection.titles = _selected_tests(options, manifest, flags["select"], environment)
    except Exception as exc:  # noqa: BLE001 - a --select naming nothing is a mistake, caught here
        return fault(str(exc), USAGE)

    if selection.failed:
        selection.failed_ids = set(runs.last_failed(manifest.root, environment))

    for argument in flags["report"]:
        try:
            reports.parse(argument)
        except ReportError as exc:
            return fault(str(exc), USAGE)

    from . import (
        plugin,
    )

    try:
        shard = _shard(flags.get("shard", ""))
        jobs = _jobs(flags.get("jobs", "auto"))
    except ValueError as exc:
        return fault(str(exc), USAGE)

    if flags.get("namespace"):
        os.environ[naming.VARIABLE] = str(flags["namespace"])
    selection.seed = flags.get("seed")
    if flags.get("shuffle") and selection.seed is None:
        selection.seed = random.randrange(1_000_000)

    confined: set[str] | None = None
    if flags.get("tests_from"):
        try:
            written_down = Path(str(flags["tests_from"])).read_text(encoding="utf-8")
        except OSError as exc:
            return fault(str(exc), USAGE)
        confined = {line.strip() for line in written_down.splitlines() if line.strip()}

    plugin.SELECTION = selection
    plugin.NO_MAKE = flags["no_make"]
    plugin.MANIFEST = manifest
    plugin.SHARD = shard
    plugin.SEED = selection.seed
    plugin.ONLY = confined
    plugin.ACCEPT = bool(flags.get("accept"))
    plugin.DRAFTED = {}
    started = runs.now()

    explaining = bool(flags.get("explaining"))
    # Drafting writes into the files a run is reading, so it never happens in more than one process.
    over_workers = jobs > 1 and not flags["dry_run"] and not explaining and not plugin.ACCEPT
    if over_workers:
        return _over_workers(options, manifest, environment, selection, jobs, started, flags)

    collected = Collected()
    named = [_locate(manifest, one) for one in flags.get("tests", ())]
    where = [str(manifest.specs)]
    if flags.get("contract"):
        where.append(str(CONTRACT))
    # No `-p atf.plugin`: ATF is a pytest plugin by entry point, so naming it here loads it a second
    # time and pytest warns that it can no longer rewrite its assertions.
    arguments = [*(named or where), "--rootdir", str(manifest.root)]
    if flags["keyword"]:
        arguments += ["-k", flags["keyword"]]
    if options.quiet or explaining:
        arguments.append("-q")
    if flags["dry_run"] or explaining:
        arguments.append("--collect-only")

    if explaining:
        with contextlib.redirect_stdout(io.StringIO()):
            status_code = pytest.main(arguments, plugins=[collected])
    else:
        status_code = pytest.main(arguments, plugins=[collected])
    laid_out = plugin.SCHEDULE
    beyond = plugin.undeclared()
    drafted = dict(plugin.DRAFTED)
    _forget(plugin)

    if status_code == pytest.ExitCode.USAGE_ERROR:
        return fault("this suite cannot be run as written; see the message above", INVALID)
    if status_code == pytest.ExitCode.INTERRUPTED:
        return fault("interrupted; nothing was recorded", USAGE)

    if explaining:
        return _explained(laid_out)
    if flags["dry_run"]:
        return Answer(
            lines=[*collected.collected, f"{len(collected.collected)} tests selected"],
            data={"tests": collected.collected},
        )

    return _finish(manifest, environment, selection, collected.finish(), started, flags, beyond, drafted)


def _import_run(manifest: Any, environment: str, flags: dict[str, Any]) -> Answer:
    """Bring a run recorded elsewhere into this suite's history. A flag on `run`, not a command."""
    try:
        imported = reports.read(Path(str(flags["import_"])), str(flags["format_"]))
    except ReportError as exc:
        return fault(str(exc), USAGE)
    imported.id = runs.new_id()
    imported.environment = environment
    imported.source = "imported"
    imported.started = imported.started or runs.now()
    imported.finished = imported.finished or imported.started
    path = runs.save(manifest.root, imported)
    return Answer(
        lines=[f"imported {len(imported.outcomes)} outcomes into {environment} as {imported.id}"],
        data={"id": imported.id, "environment": environment, "path": str(path)},
    )


def _finish(
    manifest: Any,
    environment: str,
    selection: Selection,
    outcomes: list[Any],
    started: str,
    flags: dict[str, Any],
    beyond: dict[str, list[str]] | None = None,
    drafted: dict[str, int] | None = None,
    say_failures: bool = False,
) -> Answer:
    """Record what a run did, write its reports, and say so in one line."""
    finished = build_run(environment, manifest.root, selection, outcomes, started)
    if not flags.get("no_record"):
        runs.save(manifest.root, finished)

    written = [str(reports.write(argument, finished)) for argument in flags["report"]]
    counts = finished.counts
    lines: list[str] = []
    if say_failures:
        # A run over workers has to report what a run in one process reports. Otherwise "it
        # parallelises itself" quietly costs you the failure message, which is the one thing a red
        # run is for.
        for outcome in finished.outcomes:
            if outcome.outcome is not Outcome.FAILED or outcome.failed_at is None:
                continue
            lines.append(f"✗ {outcome.test}")
            lines += [f"  {one}" for one in str(outcome.failed_at.message).splitlines()]
            lines.append("")
    lines += [
        f"{counts[Outcome.FAILED]} failed, {counts[Outcome.PASSED]} passed, "
        f"{counts[Outcome.SKIPPED]} skipped   ({finished.id})"
    ]
    if selection.seed is not None:
        lines[0] += f"   seed {selection.seed}"
    if drafted:
        from . import accept

        lines += accept.summary(drafted)
    if beyond:
        lines.append(f"{len(beyond)} tests reached a thing their sentences never named")
        lines += [f"  {test}: {', '.join(names)}" for test, names in sorted(beyond.items())]
    lines += [f"wrote {path}" for path in written]
    if counts[Outcome.FAILED]:
        lines.append("")
        lines.append("→ atf enter")
    return Answer(
        code=FAILED if counts[Outcome.FAILED] else OK,
        lines=lines,
        data={**finished.as_json(), "reports": written, "undeclared": beyond or {}, "drafted": drafted or {}},
    )


def _forget(plugin: Any) -> None:
    """Put the plugin's per-run settings back, so one process may run a suite twice."""
    plugin.SELECTION, plugin.NO_MAKE, plugin.MANIFEST = None, False, None
    plugin.SHARD, plugin.SEED, plugin.ONLY = None, None, None
    plugin.ACCEPT, plugin.DRAFTED = False, {}


def _shard(written: str) -> tuple[int, int] | None:
    """`--shard 2/5` as a pair, or nothing where the flag was not given."""
    if not written:
        return None
    index, separator, total = written.partition("/")
    if not separator or not index.isdigit() or not total.isdigit():
        raise ValueError(f"--shard takes I/N, and it was given {written!r}")
    one, many = int(index), int(total)
    if not 1 <= one <= many:
        raise ValueError(f"--shard {written}: the index runs from 1 to {many}")
    return one, many


def _jobs(written: str) -> int:
    """How many tests may be in flight at once. `auto` is one per core, and is the default."""
    if written == "auto":
        return max(1, (os.cpu_count() or 2) - 1)
    if not written.isdigit() or int(written) < 1:
        raise ValueError(f"--jobs takes a whole number or `auto`, and it was given {written!r}")
    return int(written)


def _explained(laid_out: Any) -> Answer:
    """What can run beside what, and what each thing standing alone is waiting on."""
    if laid_out is None:
        return Answer(lines=["nothing was collected"], data={"parallel": [], "serial": []})
    counts = laid_out.counts
    total = counts["parallel"] + counts["serial"]
    lines = [f"{total} tests"]
    lines.append(f"  {counts['parallel']} can run beside something else, in {counts['groups']} sets")
    lines.append(f"  {counts['serial']} run alone")
    tally: dict[str, int] = {}
    for why in laid_out.reasons.values():
        tally[why] = tally.get(why, 0) + 1
    lines += [f"      {count:>4}  {why}" for why, count in sorted(tally.items(), key=lambda one: -one[1])]
    for group in laid_out.parallel:
        lines.append(f"  set of {len(group)}")
        lines += [f"      {one}" for one in group]
    return Answer(
        lines=lines,
        data={
            "parallel": [list(group) for group in laid_out.parallel],
            "serial": list(laid_out.serial),
            "reasons": dict(laid_out.reasons),
            "counts": counts,
        },
    )


def _buckets(groups: list[tuple[str, ...]], many: int) -> list[list[str]]:
    """Deal conflict sets out over so many workers, largest first, keeping each set whole."""
    out: list[list[str]] = [[] for _ in range(many)]
    for group in sorted(groups, key=len, reverse=True):
        smallest = min(range(many), key=lambda slot: (len(out[slot]), slot))
        out[smallest].extend(group)
    return [one for one in out if one]


def _over_workers(
    options: Options,
    manifest: Any,
    environment: str,
    selection: Selection,
    jobs: int,
    started: str,
    flags: dict[str, Any],
) -> Answer:
    """Run the sets that cannot interfere at the same time, then the rest with nothing beside them."""
    laid_out = _collect_only(options, manifest, flags)
    if laid_out is None:
        return fault("this suite cannot be run as written; see the message above", INVALID)

    outcomes: list[Any] = []
    with tempfile.TemporaryDirectory(prefix="atf-run-") as where:
        rounds = [_buckets(list(laid_out.parallel), jobs), [list(laid_out.serial)]]
        for number, round_ in enumerate(rounds):
            batch = [one for one in round_ if one]
            if not batch:
                continue
            with futures.ThreadPoolExecutor(max_workers=len(batch)) as pool:
                answers = list(
                    pool.map(
                        lambda pair: _one_worker(
                            options, manifest, environment, where, *pair, shaping=_shaping(flags)
                        ),
                        [(f"{number}-{slot}", tests) for slot, tests in enumerate(batch)],
                    )
                )
            for answer in answers:
                outcomes += answer

    return _finish(manifest, environment, selection, outcomes, started, flags, say_failures=True)


def _collect_only(options: Options, manifest: Any, flags: dict[str, Any]) -> Any:
    """Lay the run out without running any of it."""
    from . import plugin

    named = [_locate(manifest, one) for one in flags.get("tests", ())]
    where = [str(manifest.specs)]
    if flags.get("contract"):
        where.append(str(CONTRACT))
    arguments = [*(named or where), "--rootdir", str(manifest.root), "--collect-only", "-q"]
    if flags["keyword"]:
        arguments += ["-k", flags["keyword"]]
    with contextlib.redirect_stdout(io.StringIO()):
        status_code = pytest.main(arguments, plugins=[Collected()])
    laid_out = plugin.SCHEDULE
    return None if status_code == pytest.ExitCode.USAGE_ERROR else laid_out


def _shaping(flags: dict[str, Any]) -> list[str]:
    """The flags that change what a run *does*, which every worker must be given.

    A worker is `atf run` against the same manifest, confined to identities it was handed. What it
    must not be is a differently-shaped run: `--no-make` in one process and not in another is a
    suite that disagrees with itself about whether anything was made.
    """
    out: list[str] = []
    if flags.get("no_make"):
        out.append("--no-make")
    if flags.get("contract"):
        out.append("--contract")
    if flags.get("namespace"):
        out += ["--namespace", str(flags["namespace"])]
    return out


def _one_worker(
    options: Options,
    manifest: Any,
    environment: str,
    where: str,
    name: str,
    tests: list[str],
    shaping: list[str] | None = None,
) -> list[Any]:
    """One worker process, and the outcomes it reported."""
    listing = Path(where) / f"{name}.txt"
    listing.write_text("\n".join(tests) + "\n", encoding="utf-8")
    reported = Path(where) / f"{name}.json"
    finished = subprocess.run(
        [
            sys.executable,
            "-m",
            "atf",
            "run",
            "--quiet",
            "--config",
            str(manifest.path),
            "--env",
            environment,
            "--jobs",
            "1",
            "--no-record",
            *(shaping or []),
            "--tests-from",
            str(listing),
            "--report",
            f"ctrf:{reported}",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=manifest.root,
        env=naming.hand_to(dict(os.environ), f"{naming.current()}-{name}"),
    )
    try:
        return reports.read(reported).outcomes
    except (ReportError, OSError):
        said = (finished.stderr or finished.stdout).strip().splitlines()
        return [
            runs.TestOutcome(
                test=one,
                outcome=Outcome.FAILED,
                failed_at=runs.Where(message=said[-1] if said else runs.STRANDED),
            )
            for one in tests
        ]


def main() -> int:
    """The console script. Click's own exit code for a bad invocation is already ATF's `2`."""
    return cli.main(standalone_mode=True, obj=Options())


if __name__ == "__main__":
    sys.exit(main())
