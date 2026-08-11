"""The `atf` entry point: the command tree, `atf run`, and the three exit codes."""

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
from .runner import Collected, Selection, SelectionError, build_run, resources_reaching
from .runs import Outcome


@dataclass
class Options:
    """The flags every subcommand accepts, carried on Click's context."""

    as_json: bool = False
    config: str | None = None
    quiet: bool = False


def globals_too(command: Any) -> Any:
    """Let the global flags be written after the subcommand as well as before it.

    Both positions are accepted. Click parses each; this says the later one wins.
    """
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
    """Run a subcommand, emit its answer, and exit with its code.

    Anything unhandled becomes "the question could not be asked", with exit code `2`.
    """
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
    """Declared resources, and the tests that need them."""
    context.obj = Options(as_json=as_json, config=config, quiet=quiet)
    if context.invoked_subcommand is None:
        click.echo(context.get_help())


@cli.command()
@globals_too
@click.option("--env", default="local", show_default=True, help="name of the single environment written")
@click.option("--force", is_flag=True, help="overwrite an existing atf.yaml")
@click.pass_context
def init(context: click.Context, **flags: Any) -> None:
    """Write an atf.yaml, an empty resources.py and an empty specs/."""
    _adopt(context, flags)
    _guarded(context, lambda: commands.do_init(env=flags["env"], force=flags["force"]))


@cli.command()
@globals_too
@click.argument("env", required=False, default="")
@click.argument("names", nargs=-1)
@click.option("--absent-only", is_flag=True, help="list only what is not present")
@click.pass_context
def status(context: click.Context, **flags: Any) -> None:
    """Where each resource stands. Never gates: 0 or 2, and never 1."""
    _adopt(context, flags)
    _guarded(
        context,
        lambda: commands.do_status(
            flags["env"],
            list(flags["names"]),
            absent_only=flags["absent_only"],
            config=context.obj.config,
        ),
    )


@cli.command()
@globals_too
@click.argument("env", required=False, default="")
@click.argument("names", nargs=-1)
@click.option("--dry-run", is_flag=True, help="say what would change, and change nothing")
@click.pass_context
def make(context: click.Context, **flags: Any) -> None:
    """Make each resource, and everything it needs, parents first."""
    _adopt(context, flags)
    _guarded(
        context,
        lambda: commands.do_make(
            flags["env"], list(flags["names"]), dry_run=flags["dry_run"], config=context.obj.config
        ),
    )


@cli.command()
@globals_too
@click.option("--env", default="", help="environment to run against; default_env unless given")
@click.option("--tag", multiple=True, help="only tests carrying this tag; repeatable, OR")
@click.option("--select", default="", help="only tests naming this resource; a leading + widens downstream")
@click.option("--failed", is_flag=True, help="only tests whose last outcome here was failed")
@click.option("--report", multiple=True, metavar="FORMAT:PATH", help="write a report; repeatable")
@click.option("--no-make", is_flag=True, help="do not make missing resources")
@click.option("--dry-run", is_flag=True, help="print the selected identities and exit 0")
@click.option("-k", "keyword", default="", help="only tests whose identity matches this expression")
@click.option("--jobs", default="1", metavar="N|auto", help="run tests that cannot interfere at the same time")
@click.option("--shard", default="", metavar="I/N", help="run one slice of the laid-out run")
@click.option("--seed", type=int, default=None, help="run the selected tests in this order")
@click.option("--shuffle", is_flag=True, help="run them in an order nothing chose, and record the seed")
@click.option("--explain", is_flag=True, help="say what can run beside what, and run nothing")
@click.option("--tests-from", default="", metavar="PATH", help="confine this run to the identities in this file")
@click.option("--no-record", is_flag=True, help="run and report, and leave history alone")
@click.option("--namespace", default="", help="the token a factory builds recognition values from")
@click.argument("tests", nargs=-1, metavar="[TEST]...")
@click.pass_context
def run(context: click.Context, **flags: Any) -> None:
    """Run tests and record a run. A named TEST is one identity, as `atf docs` and the editor spell it."""
    _adopt(context, flags)
    _guarded(context, lambda: do_run(context.obj, **flags))


@cli.command()
@globals_too
@click.argument("env", required=False, default="")
@click.argument("names", nargs=-1)
@click.option("--strict", is_flag=True, help="exit 1 when anything has moved")
@click.pass_context
def drift(context: click.Context, **flags: Any) -> None:
    """What this environment holds that no longer matches its declaration."""
    _adopt(context, flags)
    _guarded(
        context,
        lambda: commands.do_drift(
            flags["env"], list(flags["names"]), strict=flags["strict"], config=context.obj.config
        ),
    )


@cli.command()
@globals_too
@click.argument("name", required=False, default="")
@click.option("--tests-only", is_flag=True, help="list the affected tests only")
@click.option("--resources-only", is_flag=True, help="list the affected resources only")
@click.option("--depth", type=int, default=0, help="follow lineage this many steps")
@click.option("--since", default="", metavar="REV", help="what a change since this revision could have broken")
@click.pass_context
def impact(context: click.Context, **flags: Any) -> None:
    """What breaks if a resource does. Reads the graph, not history."""
    _adopt(context, flags)
    _guarded(
        context,
        lambda: commands.do_impact(
            flags["name"],
            tests_only=flags["tests_only"],
            resources_only=flags["resources_only"],
            depth=flags["depth"],
            since=flags["since"],
            config=context.obj.config,
        ),
    )


@cli.command()
@globals_too
@click.argument("env", required=False, default="")
@click.option("--out", default="", metavar="PATH", help="write the source here instead of to stdout")
@click.option("--force", is_flag=True, help="overwrite a file that already declares resources")
@click.pass_context
def adopt(context: click.Context, **flags: Any) -> None:
    """Write the declarations for what an environment already holds."""
    _adopt(context, flags)
    _guarded(
        context,
        lambda: commands.do_adopt(
            flags["env"], out=flags["out"], force=flags["force"], config=context.obj.config
        ),
    )


@cli.command("verify-adapter")
@globals_too
@click.argument("name")
@click.option("--env", default="", help="which environment to write in; default_env unless given")
@click.pass_context
def verify_adapter(context: click.Context, **flags: Any) -> None:
    """Put a resource's adapter through the contract, against a copy it marks and removes."""
    _adopt(context, flags)
    _guarded(
        context, lambda: commands.do_verify_adapter(flags["name"], flags["env"], config=context.obj.config)
    )


@cli.command("why-red")
@globals_too
@click.argument("test")
@click.option("--env", default="", help="whose history to read; default_env unless given")
@click.pass_context
def why_red(context: click.Context, **flags: Any) -> None:
    """When a test turned, and the revision on either side of the turn."""
    _adopt(context, flags)
    _guarded(context, lambda: commands.do_why_red(flags["test"], flags["env"], config=context.obj.config))


@cli.command()
@globals_too
@click.option("--strict", is_flag=True, help="exit 1 when anything is unused, so CI can gate on it")
@click.option(
    "--kind",
    multiple=True,
    type=click.Choice(["resources", "phrases", "steps"]),
    help="restrict to one kind; repeatable",
)
@click.pass_context
def unused(context: click.Context, **flags: Any) -> None:
    """What nothing asks for."""
    _adopt(context, flags)
    _guarded(
        context,
        lambda: commands.do_unused(
            strict=flags["strict"], kinds=list(flags["kind"]), config=context.obj.config
        ),
    )


@cli.command()
@globals_too
@click.option("--out", default="./atf-docs", show_default=True, metavar="DIRECTORY", help="where to write")
@click.option("--env", default="", help="whose history supplies the verdicts; default_env unless given")
@click.option("--no-verdicts", is_flag=True, help="render the specs alone; do not read history")
@click.pass_context
def docs(context: click.Context, **flags: Any) -> None:
    """Render the specs as markdown, with the verdict each scenario last had."""
    _adopt(context, flags)
    _guarded(
        context,
        lambda: commands.do_docs(
            out=flags["out"],
            env=flags["env"],
            no_verdicts=flags["no_verdicts"],
            config=context.obj.config,
        ),
    )


@cli.command()
@globals_too
@click.option("--strict", is_flag=True, help="also treat an unused resource or phrase as a fault")
@click.pass_context
def check(context: click.Context, **flags: Any) -> None:
    """Every registered check, over this suite. Exits 1 on findings — they are its answer."""
    _adopt(context, flags)
    _guarded(context, lambda: commands.do_check(strict=flags["strict"], config=context.obj.config))


@cli.command("import-run")
@globals_too
@click.argument("env")
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("--format", "format_", default="ctrf", show_default=True, help="which registered format")
@click.option("--label", default="imported", show_default=True, help="recorded on the run, so CI is told apart")
@click.option("--revision", default="", help="override the revision; taken from the file by default")
@click.pass_context
def import_run(context: click.Context, **flags: Any) -> None:
    """Bring a run recorded elsewhere into this suite's history."""
    _adopt(context, flags)
    _guarded(
        context,
        lambda: commands.do_import_run(
            flags["env"],
            flags["file"],
            flags["format_"],
            label=flags["label"],
            revision=flags["revision"],
            config=context.obj.config,
        ),
    )


@cli.command()
@globals_too
@click.option("--env", default="", help="environment to open on; default_env unless given")
@click.option("--port", default=8765, type=int, show_default=True, help="which port")
@click.option("--mcp", is_flag=True, help="serve the same operations to an agent instead")
@click.pass_context
def edit(context: click.Context, **flags: Any) -> None:
    """Start a local server that reads and drives this suite."""
    _adopt(context, flags)
    from .editor import serve  # noqa: PLC0415 - only this command needs a web server

    config = context.obj.config
    manifest = Path(config) if config else None
    if flags["mcp"]:
        from .agent import serve as serve_agent  # noqa: PLC0415
        from .editor import Editor  # noqa: PLC0415

        try:
            serve_agent(Editor(manifest, flags["env"]))
        except RuntimeError as exc:
            message = str(exc)
            _guarded(context, lambda: fault(message, USAGE))
        return
    serve(manifest, flags["env"], flags["port"])


@cli.command()
@globals_too
@click.option("--env", default="", help="which environment")
@click.pass_context
def history(context: click.Context, **flags: Any) -> None:
    """Past runs of one environment, oldest first."""
    _adopt(context, flags)
    _guarded(context, lambda: commands.do_history(flags["env"], config=context.obj.config))


# --- The one subcommand that executes anything ---------------------------------------------------


def _locate(manifest: Any, identity: str) -> str:
    """Where a named test lives, whether it was written from the suite root or from `specs/`.

    A test identity is `<file>::<title>`. History and reports carry the file from the suite root;
    somebody typing one at a shell writes it from `specs/`.
    """
    where, separator, title = identity.partition("::")
    for root in (manifest.root, manifest.specs):
        candidate = root / where
        if candidate.is_file():
            return f"{candidate}{separator}{title}"
    return str(manifest.specs / identity)


def do_run(options: Options, **flags: Any) -> Answer:
    """Run tests and record a run.

    Exits `0` when no test failed — **including a selection that legitimately matched nothing**.
    Exits `1` when at least one did. Exits `2` when the run never started, in which case nothing was
    recorded.
    """
    try:
        manifest = load(Path(options.config)) if options.config else load()
        suite = load_suite(manifest)
    except ManifestError as exc:
        return fault(str(exc), USAGE)
    except SuiteError as exc:
        return fault(str(exc), INVALID)

    environment = flags["env"] or manifest.default_env
    if environment not in manifest.environments:
        known = ", ".join(sorted(manifest.environments)) or "none"
        return fault(f"no environment {environment!r} in this manifest (known: {known})", USAGE)

    selection = Selection(
        tags=list(flags["tag"]),
        select=flags["select"],
        failed=flags["failed"],
        keyword=flags["keyword"],
    )
    try:
        # A `--select` naming something the suite does not declare is a mistake, caught here so that
        # nothing runs and nothing is recorded.
        if selection.select:
            resources_reaching(suite, selection.resource, downstream=selection.downstream)
    except SelectionError as exc:
        return fault(str(exc), USAGE)

    if selection.failed:
        selection.failed_ids = set(runs.last_failed(manifest.root, environment))

    for argument in flags["report"]:
        try:
            reports.parse(argument)
        except ReportError as exc:
            return fault(str(exc), USAGE)

    from . import plugin  # noqa: PLC0415 - importing it configures nothing until pytest starts

    try:
        shard = _shard(flags.get("shard", ""))
        jobs = _jobs(flags.get("jobs", "1"))
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
    started = runs.now()

    explaining = bool(flags.get("explain"))
    if jobs > 1 and not flags["dry_run"] and not explaining:
        return _over_workers(options, manifest, environment, selection, jobs, started, flags)

    collected = Collected()

    # A named test is a path pytest can collect, so `atf run "lists.feature::a list …"` names one
    # identity where `-k` names a pattern. `-k` cannot: its expression language has no room for a
    # sentence with spaces in it.
    named = [_locate(manifest, one) for one in flags.get("tests", ())]
    # No `-p atf.plugin`: ATF is a pytest plugin by entry point, so naming it here loads it a second
    # time and pytest warns that it can no longer rewrite its assertions.
    arguments = [*(named or [str(manifest.specs)]), "--rootdir", str(manifest.root)]
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

    return _finish(manifest, environment, selection, collected.finish(), started, flags, beyond)


def _finish(
    manifest: Any,
    environment: str,
    selection: Selection,
    outcomes: list[Any],
    started: str,
    flags: dict[str, Any],
    beyond: dict[str, list[str]] | None = None,
) -> Answer:
    """Record what a run did, write its reports, and say so in one line."""
    finished = build_run(environment, manifest.root, selection, outcomes, started)
    if not flags.get("no_record"):
        runs.save(manifest.root, finished)

    written = [str(reports.write(argument, finished)) for argument in flags["report"]]
    counts = finished.counts
    lines = [
        f"{counts[Outcome.FAILED]} failed, {counts[Outcome.PASSED]} passed, "
        f"{counts[Outcome.SKIPPED]} skipped   ({finished.id})"
    ]
    if selection.seed is not None:
        lines[0] += f"   seed {selection.seed}"
    if beyond:
        lines.append(f"{len(beyond)} tests reached a resource their sentences never named")
        lines += [f"  {test}: {', '.join(names)}" for test, names in sorted(beyond.items())]
    lines += [f"wrote {path}" for path in written]
    return Answer(
        code=FAILED if counts[Outcome.FAILED] else OK,
        lines=lines,
        data={**finished.as_json(), "reports": written, "undeclared": beyond or {}},
    )


def _forget(plugin: Any) -> None:
    """Put the plugin's per-run settings back, so one process may run a suite twice."""
    plugin.SELECTION, plugin.NO_MAKE, plugin.MANIFEST = None, False, None
    plugin.SHARD, plugin.SEED, plugin.ONLY = None, None, None


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
    """How many tests may be in flight at once. `auto` is one per core."""
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
    lines += [
        f"      {count:>4}  {why}" for why, count in sorted(tally.items(), key=lambda one: -one[1])
    ]
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
    """Run the sets that cannot interfere at the same time, then the rest with nothing beside them.

    Every worker is `atf run` against the same manifest, confined to identities it was handed.
    """
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
                        lambda pair: _one_worker(options, manifest, environment, where, *pair),
                        [(f"{number}-{slot}", tests) for slot, tests in enumerate(batch)],
                    )
                )
            for answer in answers:
                outcomes += answer

    return _finish(manifest, environment, selection, outcomes, started, flags)


def _collect_only(options: Options, manifest: Any, flags: dict[str, Any]) -> Any:
    """Lay the run out without running any of it."""
    from . import plugin  # noqa: PLC0415

    named = [_locate(manifest, one) for one in flags.get("tests", ())]
    arguments = [
        *(named or [str(manifest.specs)]),
        "--rootdir",
        str(manifest.root),
        "--collect-only",
        "-q",
    ]
    if flags["keyword"]:
        arguments += ["-k", flags["keyword"]]
    with contextlib.redirect_stdout(io.StringIO()):
        status_code = pytest.main(arguments, plugins=[Collected()])
    laid_out = plugin.SCHEDULE
    return None if status_code == pytest.ExitCode.USAGE_ERROR else laid_out


def _one_worker(
    options: Options, manifest: Any, environment: str, where: str, name: str, tests: list[str]
) -> list[Any]:
    """One worker process, and the outcomes it reported."""
    listing = Path(where) / f"{name}.txt"
    listing.write_text("\n".join(tests) + "\n", encoding="utf-8")
    reported = Path(where) / f"{name}.json"
    finished = subprocess.run(  # noqa: S603
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
            "--no-record",
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
