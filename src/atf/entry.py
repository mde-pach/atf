"""The `atf` entry point: the command tree, `atf run`, and the three exit codes.

**Exit codes are coarse; the reason travels in the message.** `0` passed, `1` a test failed, `2` the
run never started. For the commands that do not run tests, read them as: the question was answered,
the answer is no, the question could not be asked.

The global flags — `--json`, `--config`, `--quiet` — are accepted **before or after** the
subcommand. Both positions are real: a manifest's `command: { prefix: "atf --config ..." }` can only
put them first, and `atf make readonly --json` reads naturally with them last.

`run` is the only subcommand that executes anything, so it is the only one that owns a pytest
invocation. Everything else answers from the graph, the manifest or the history, and lives in
[commands](commands.py).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
import pytest

from . import __version__, commands, record, reports
from .commands import FAILED, INVALID, NEVER_STARTED, OK, USAGE, Answer, fault
from .loader import SuiteError, load_suite
from .manifest import ManifestError, load
from .record import Outcome
from .reports import ReportError
from .runner import Collected, Selection, SelectionError, build_run, resources_reaching


@dataclass
class Options:
    """What every subcommand accepts, carried on Click's context rather than re-merged per command."""

    as_json: bool = False
    config: str | None = None
    quiet: bool = False


def globals_too(command: Any) -> Any:
    """Let the global flags be written after the subcommand as well as before it.

    Both positions are real. A manifest's `command: { prefix: "atf --config ..." }` can only put
    them first, and `atf make readonly --json` reads naturally with them last. Click parses each
    position; this only says the later one wins, in one place rather than per command.
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

    Anything unhandled becomes "the question could not be asked" rather than a traceback, because a
    traceback is not an exit code a pipeline can read.
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
@click.version_option(__version__, "--version", message="%(version)s")
@click.pass_context
def cli(context: click.Context, as_json: bool, config: str | None, quiet: bool) -> None:
    """Declared resources, and the tests that need them."""
    context.obj = Options(as_json=as_json, config=config, quiet=quiet)
    if context.invoked_subcommand is None:
        click.echo(context.get_help())


@cli.command()
@globals_too
@click.option("--env", default="local", help="name of the single environment written")
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
@click.pass_context
def status(context: click.Context, **flags: Any) -> None:
    """Where each resource stands. Never gates: 0 or 2, and never 1."""
    _adopt(context, flags)
    _guarded(
        context,
        lambda: commands.do_status(flags["env"], list(flags["names"]), config=context.obj.config),
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
@click.option("--env", default="", help="environment to run against")
@click.option("--tag", multiple=True, help="only tests carrying this tag; repeatable, OR")
@click.option("--select", default="", help="only tests naming this resource; a leading + widens downstream")
@click.option("--failed", is_flag=True, help="only tests whose last outcome here was failed")
@click.option("--report", multiple=True, metavar="FORMAT:PATH", help="write a report; repeatable")
@click.option("--no-make", is_flag=True, help="do not make missing resources")
@click.option("--dry-run", is_flag=True, help="print the selected identities and exit 0")
@click.option("-k", "keyword", default="", help="only tests whose identity matches this expression")
@click.pass_context
def run(context: click.Context, **flags: Any) -> None:
    """Run tests and record a run."""
    _adopt(context, flags)
    _guarded(context, lambda: do_run(context.obj, **flags))


@cli.command()
@globals_too
@click.argument("name", required=False, default="")
@click.option("--tests-only", is_flag=True, help="list the affected tests only")
@click.option("--resources-only", is_flag=True, help="list the affected resources only")
@click.option("--depth", type=int, default=0, help="follow lineage this many steps")
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
            config=context.obj.config,
        ),
    )


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
@click.pass_context
def check(context: click.Context, **flags: Any) -> None:
    """Every registered check, over this suite. Exits 1 on findings — they are its answer."""
    _adopt(context, flags)
    _guarded(context, lambda: commands.do_check(config=context.obj.config))


@cli.command("import-run")
@globals_too
@click.argument("env")
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("--format", "format_", default="ctrf", help="which registered format (default ctrf)")
@click.pass_context
def import_run(context: click.Context, **flags: Any) -> None:
    """Bring a run recorded elsewhere into this suite's history."""
    _adopt(context, flags)
    _guarded(
        context,
        lambda: commands.do_import_run(
            flags["env"], flags["file"], flags["format_"], config=context.obj.config
        ),
    )


@cli.command()
@globals_too
@click.option("--env", default="", help="which environment to open on")
@click.option("--host", default="127.0.0.1", help="where to serve; local by default, and on purpose")
@click.option("--port", default=8765, type=int, help="which port")
@click.option("--mcp", is_flag=True, help="serve the same operations to an agent instead")
@click.pass_context
def edit(context: click.Context, **flags: Any) -> None:
    """Start a local server that reads and drives this suite."""
    _adopt(context, flags)
    from .editor import serve  # noqa: PLC0415 - only this command needs a web server

    config = context.obj.config
    if flags["mcp"]:
        click.echo("`--mcp` is not built yet; the same answers are under /api/<view>.", err=True)
    serve(Path(config) if config else None, flags["env"], flags["host"], flags["port"])


@cli.command()
@globals_too
@click.option("--env", default="", help="which environment")
@click.pass_context
def history(context: click.Context, **flags: Any) -> None:
    """Past runs of one environment, oldest first."""
    _adopt(context, flags)
    _guarded(context, lambda: commands.do_history(flags["env"], config=context.obj.config))


# --- The one subcommand that executes anything ---------------------------------------------------


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
        selection.failed_ids = set(record.last_failed(manifest.root, environment))

    for argument in flags["report"]:
        try:
            reports.parse(argument)
        except ReportError as exc:
            return fault(str(exc), USAGE)

    from . import plugin  # noqa: PLC0415 - importing it configures nothing until pytest starts

    plugin.SELECTION = selection
    plugin.NO_MAKE = flags["no_make"]
    plugin.MANIFEST = manifest
    collected = Collected()
    started = record.now()

    arguments = [str(manifest.specs), "-p", "atf.plugin", "--rootdir", str(manifest.root)]
    if flags["keyword"]:
        arguments += ["-k", flags["keyword"]]
    if options.quiet:
        arguments.append("-q")
    if flags["dry_run"]:
        arguments.append("--collect-only")

    status_code = pytest.main(arguments, plugins=[collected])
    plugin.SELECTION, plugin.NO_MAKE, plugin.MANIFEST = None, False, None

    if status_code == pytest.ExitCode.USAGE_ERROR:
        return fault("this suite cannot be run as written; see the message above", INVALID)
    if status_code == pytest.ExitCode.INTERRUPTED:
        return fault("interrupted; nothing was recorded", USAGE)

    if flags["dry_run"]:
        return Answer(
            lines=[*collected.collected, f"{len(collected.collected)} tests selected"],
            data={"tests": collected.collected},
        )

    outcomes = collected.finish()
    finished = build_run(environment, manifest.root, selection, outcomes, started)
    record.save(manifest.root, finished)

    written = [str(reports.write(argument, finished)) for argument in flags["report"]]
    counts = finished.counts
    lines = [
        f"{counts[Outcome.FAILED]} failed, {counts[Outcome.PASSED]} passed, "
        f"{counts[Outcome.SKIPPED]} skipped   ({finished.id})"
    ]
    lines += [f"wrote {path}" for path in written]
    return Answer(
        code=FAILED if counts[Outcome.FAILED] else OK,
        lines=lines,
        data={**finished.as_json(), "reports": written},
    )


def main() -> int:
    """The console script. Click's own exit code for a bad invocation is already ATF's `2`."""
    return cli.main(standalone_mode=True, obj=Options())


if __name__ == "__main__":
    sys.exit(main())
