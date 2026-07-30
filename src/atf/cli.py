"""The `atf` command: init, serve, seed, status, run, lint, docs, import, import-run."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Any

from .engine.bootstrap import bootstrap
from .engine.status import BLOCKED, CREATED, PRESENT, ProvisionResult
from .model.catalog import CatalogError
from .model.manifest import ConfigError, load_manifest, resolve_env, resolve_env_refs, resolve_manifest
from .model.text import plural
from .model.typespec import DATA, EPHEMERAL, REFERENCE
from .run.report import as_ctrf
from .run.runner import ERROR, FAILED, RunRecord, failed_ids
from .run.runner import run as run_tests
from .run.store import ReportError, RunStore
from .suite import openapi
from .suite.lint import check as lint_specs
from .suite.lint import report as lint_report
from .suite.scaffold import MANIFEST_FILE, scaffold

# `atf docs` is the only command that needs [discovery](discovery.py), and discovery is the most
# expensive module in the framework to import. So it is imported inside the handler that uses it,
# and the one thing the *parser* needs from it — the default in a help string — is named here.
# Every other command saves the whole of it.
DEFAULT_DOCS_OUT = "docs/specs"

BANNER = """\
ATF cockpit — {url}
  This cockpit performs mutating actions against real environments and has NO authentication.
  It binds {host} by design; for shared access put it behind an authenticating reverse proxy.
  Mutable environments: {mutable}
"""


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (ConfigError, CatalogError, openapi.SchemaError) as exc:
        print(f"atf: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atf", description="Another Test Framework")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="scaffold a new suite in DIRECTORY")
    init.add_argument("directory", nargs="?", default=".", type=Path)
    init.set_defaults(handler=cmd_init)

    serve = sub.add_parser("serve", help="run the cockpit")
    serve.add_argument("--env")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument(
        "--mcp",
        action="store_true",
        help="also answer MCP, so an agent can compose scenarios from this suite's own vocabulary",
    )
    serve.set_defaults(handler=cmd_serve)

    seed = sub.add_parser("seed", help="materialize resources into an environment")
    seed.add_argument("env")
    seed.add_argument("--type", dest="resource_type")
    seed.add_argument("--name")
    seed.add_argument(
        "--keep-going",
        action="store_true",
        help="attempt independent resources after a failure instead of stopping at the first",
    )
    seed.set_defaults(handler=cmd_seed)

    status = sub.add_parser("status", help="print per-resource present/absent/ephemeral")
    status.add_argument("env")
    status.set_defaults(handler=cmd_status)

    run = sub.add_parser("run", help="run specs; nonzero exit on failure")
    run.add_argument("paths", nargs="*")
    run.add_argument("--env")
    run.add_argument("-k", dest="keyword", default="", metavar="EXPR", help="only scenarios whose name matches")
    run.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        metavar="TAG",
        help="only scenarios carrying this tag; repeat for any of several",
    )
    run.add_argument("--failed", action="store_true", help="only what did not pass in the last run here")
    run.add_argument("--json", dest="json_path", type=Path, metavar="PATH", help="also write a CTRF report here")
    run.set_defaults(handler=cmd_run)

    lint = sub.add_parser("lint", help="check that no spec line says something only the layer below should know")
    lint.set_defaults(handler=cmd_lint)

    docs = sub.add_parser("docs", help="write the features out as markdown, with the last run's verdict")
    docs.add_argument(
        "--out", default=DEFAULT_DOCS_OUT, help=f"where the pages go (default: {DEFAULT_DOCS_OUT})"
    )
    docs.add_argument("--env", help="whose run history the verdicts come from")
    docs.set_defaults(handler=cmd_docs)

    importing = sub.add_parser("import", help="derive catalog source from a schema the service publishes")
    kinds = importing.add_subparsers(dest="kind", required=True)
    from_openapi = kinds.add_parser("openapi", help="derive resource types from an OpenAPI schema")
    from_openapi.add_argument(
        "source",
        nargs="?",
        help="a path or URL; omit it to re-read the one named in the manifest under `schemas:`",
    )
    from_openapi.add_argument("--schema", help="which entry under `schemas:` to read, when there is more than one")
    from_openapi.add_argument("--apply", action="store_true", help="write the proposal instead of only showing it")
    from_openapi.set_defaults(handler=cmd_import_openapi)

    imported = sub.add_parser("import-run", help="record a pytest --json-report file from CI as a run")
    imported.add_argument("env")
    imported.add_argument("report", type=Path)
    imported.set_defaults(handler=cmd_import_run)

    return parser


# ---- commands --------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    """Scaffold a suite here. Refuses, changing nothing, when a manifest is already present.

    Anything else already in the directory is left alone and reported.
    """
    root = Path(args.directory).resolve()
    if (root / MANIFEST_FILE).is_file():
        print(
            f"{root} already contains a suite — {MANIFEST_FILE} is there, so nothing was written.\n"
            "Edit it, or run `atf init` somewhere with no suite in it.",
            file=sys.stderr,
        )
        return 2

    root.mkdir(parents=True, exist_ok=True)
    written, kept = scaffold(root, root.name)
    print(f"Scaffolded an ATF suite in {root}:")
    for path in written:
        print(f"  {path.relative_to(root)}")
    if kept:
        print("\nLeft alone, because they were already here:")
        for path in kept:
            print(f"  {path.relative_to(root)}")
    print("\nNext: `atf run` — it passes as it stands, against a stand-in backend. Then `atf serve`.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the cockpit, and — asked for it — the MCP endpoint on the same server.

    `--mcp` with no SDK installed exits 2 saying what to install, before anything is started.
    """
    import uvicorn

    from .cockpit.app import create_app

    url = f"http://{args.host}:{args.port}"
    answering = ""
    if args.mcp:
        from .agent.mcp import MOUNT, unavailable

        reason = unavailable()
        if reason:
            print(f"atf: --mcp was asked for, and {reason}", file=sys.stderr)
            return 2
        answering = f"  Answering MCP at {url}{MOUNT}/ — it can run scenarios against those environments.\n"

    manifest = load_manifest(resolve_manifest())
    app = create_app(args.env, mcp_host=args.host if args.mcp else None)
    print(BANNER.format(url=url, host=args.host, mutable=", ".join(sorted(manifest.mutable_envs)) or "none"))
    if answering:
        print(answering)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        print(f"WARNING: binding {args.host} exposes the cockpit beyond this machine.\n", file=sys.stderr)

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    boot = bootstrap(args.env)
    if not boot.manifest.is_mutable(boot.env):
        allowed = ", ".join(sorted(boot.manifest.mutable_envs)) or "none"
        print(
            f"atf: refusing to seed {boot.env!r} — it is not in `mutable_envs` (allowed: {allowed})",
            file=sys.stderr,
        )
        return 2

    engine = boot.materializer
    subset = _subset(engine, args.resource_type, args.name)
    if subset is None:
        return 2

    outcome = engine.materialize(subset, keep_going=args.keep_going)

    for result in outcome.results:
        mark = "ok" if result.ok else ("skip" if result.action == BLOCKED else "FAIL")
        detail = f" — {result.detail}" if result.detail else ""
        print(f"  [{mark:>4}] {result.node_id:<40} {result.action}{detail}")

    print("\n" + _tally(outcome.results) + f" in {boot.env}.")
    if not args.keep_going and outcome.failures:
        remaining = len(subset) - len(outcome.results)
        if remaining > 0:
            print(f"Stopped at the first failure; {remaining} resource(s) not attempted. "
                  "Re-run with --keep-going to attempt independent ones.")
    return 1 if outcome.failures else 0


def _reason(detail: str) -> str:
    """The line of a failure worth showing: what it said, not where it stopped.

    A pytest report ends with `file.py:164: Failed` — the location, which is the least useful line
    in it and the one the nodeid above has already covered. What the failure *said* is on the lines
    pytest marks with `E`, and the first of those is what a person reads. Printing the last line
    instead meant a run could say a scenario failed and never say why, which is most of what a dev
    loop is for.
    """
    lines = [line for line in detail.splitlines() if line.strip()]
    if not lines:
        return ""
    said = [line for line in lines if line.lstrip().startswith("E ")]
    return (said[0] if said else lines[-1]).strip()


def _tally(results: list[ProvisionResult]) -> str:
    """A failure counts as failed whatever it was attempting."""
    counts = {"created": 0, "already present": 0, "found": 0, "failed": 0, "blocked": 0}
    for result in results:
        if not result.ok:
            counts["blocked" if result.action == BLOCKED else "failed"] += 1
        elif result.action == CREATED:
            counts["created"] += 1
        elif result.action == REFERENCE:
            counts["found"] += 1
        else:
            counts["already present"] += 1

    parts = [f"{count} {label}" for label, count in counts.items() if count]
    return ", ".join(parts) or "nothing to do"


def cmd_status(args: argparse.Namespace) -> int:
    boot = bootstrap(args.env)
    status = boot.materializer.status()
    if not status:
        print("The catalog is empty.")
        return 0

    width = max(len(nid) for nid in status)
    for nid, entry in status.items():
        detail = f" — {entry.detail}" if entry.detail else ""
        print(f"  {nid:<{width}}  {entry.state:<12}{detail}")

    present = status.count(PRESENT)
    ephemeral = status.count(EPHEMERAL)
    total = len(status) - ephemeral
    print(f"\n{present}/{total} present in {boot.env}" + (f" ({ephemeral} built per run)" if ephemeral else ""))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    boot = bootstrap(args.env)
    store = RunStore(boot.manifest.root)

    targets = list(args.paths)
    if args.failed:
        if targets:
            print("--failed already says which tests to run, so it takes no paths.", file=sys.stderr)
            return 2
        previous = store.latest(boot.env)
        if previous is None:
            print(
                f"nothing has run in {boot.env} yet, so there is nothing to run again. "
                "Run `atf run` once first.",
                file=sys.stderr,
            )
            return 2
        targets = failed_ids(previous)
        if not targets:
            # Not a refusal and not an empty run: everything passed last time, which is the answer
            # the question deserves. Exiting nonzero here would make a green suite look broken.
            print(f"Nothing failed in the last run of {boot.env}.")
            return 0
        print(f"Running the {len(targets)} that did not pass last time in {boot.env}.\n")

    summary = run_tests(
        targets or None,
        boot.env,
        boot.manifest.root,
        boot.manifest.specs_dir,
        keyword=args.keyword,
        tags=args.tags,
    )
    record = summary.as_record(boot.env)
    # History is a convenience, not the point of the command: a read-only checkout still runs.
    with contextlib.suppress(OSError):
        store.save(record)

    for nodeid, result in sorted(summary.results.items()):
        print(f"  [{result.outcome:>7}] {nodeid}  {result.duration:.2f}s")
        if result.outcome not in {FAILED, ERROR}:
            continue
        step = result.failed_step
        if step is not None:
            print(f"           at: {step.keyword} {step.text}".rstrip())
        if result.detail:
            print(f"           {_reason(result.detail)}")

    counts = summary.counts
    print(
        f"\n{counts['passed']} passed, {counts['failed']} failed, "
        f"{counts['skipped']} skipped, {counts['error']} errored in {boot.env}"
    )
    if args.json_path is not None and not _write_ctrf(args.json_path, record):
        return 2
    if not summary.results and summary.returncode != 0:
        narrowed = _narrowing(args)
        if narrowed:
            print(f"Nothing matched {narrowed}.", file=sys.stderr)
        else:
            print(summary.output, file=sys.stderr)
    return 0 if summary.returncode == 0 else 1


def _narrowing(args: argparse.Namespace) -> str:
    """What the developer asked for, said back to them — for when it matched nothing."""
    said = []
    if args.keyword:
        said.append(f"-k {args.keyword}")
    if args.tags:
        said.append("--tag " + " --tag ".join(args.tags))
    return " ".join(said)


def _write_ctrf(path: Path, record: RunRecord) -> bool:
    """Write the run where CI will read it, or say why it could not. Never raises."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(as_ctrf(record), indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"could not write the report to {path}: {exc}", file=sys.stderr)
        return False
    print(f"Wrote a CTRF report to {path}")
    return True


def cmd_lint(args: argparse.Namespace) -> int:
    """A spec line may not name a field, a selector, a status code, a path or a CLI flag.

    Reads the feature files and nothing else: no environment, no adapters, no collection.
    """
    manifest = load_manifest(resolve_manifest())
    findings = lint_specs(manifest.specs_dir)
    print(lint_report(findings, manifest.specs_dir), file=sys.stderr if findings else sys.stdout)
    return 1 if findings else 0


def cmd_docs(args: argparse.Namespace) -> int:
    """Write the suite's features out as markdown, with what the runs so far said about each.

    The verdicts are `--env`'s, and an unknown one raises `ConfigError` naming the known ones.
    Read-only: it runs nothing, provisions nothing, and writes only under `--out`.
    """
    manifest = load_manifest(resolve_manifest())
    env = args.env or resolve_env(manifest)
    manifest.env(env)  # raises ConfigError, with the known environments, when it is not one

    from .suite import docs as living

    specs = living.read(manifest.specs_dir)
    if not specs:
        print(f"No scenarios under {manifest.specs_dir} — nothing to write.")
        return 0

    questions = living.read_questions(manifest.specs_dir)
    results = RunStore(manifest.root).merged_results(env)
    out = Path(args.out)
    out = out if out.is_absolute() else manifest.root / out
    try:
        written = living.write(living.render(specs, results, env, manifest.specs_dir, questions), out)
    except OSError as exc:
        print(f"atf: nothing written — {exc}", file=sys.stderr)
        return 2

    print(f"Wrote {plural(len(written), 'page')} under {out}:")
    for path in written:
        print(f"  {path.relative_to(out)}")
    print("\n" + living.tally(specs, results, env))
    return 0


NOT_INFERRED = """\
What a schema does not say, and this did not guess:
  mode       every type here defaults to `create`. Set `mode: reference` on anything ATF must never
             make, and `mode: data` on anything it only ever looks at.
  lifecycle  every type here defaults to `persistent`. Set `lifecycle: ephemeral` on anything built
             for one scenario and torn down with it.
  depends_on which resource needs which is a fact about your instances, not about the API — except
             where a path already scopes one under another, which is noted in the file."""


def cmd_import_openapi(args: argparse.Namespace) -> int:
    """Write the resource types an OpenAPI schema describes — once, and then only ever propose them.

    The first import writes. Every import after it stops at a diff unless `--apply`: it adds what is
    missing, leaves what is declared alone, and reports what the schema no longer agrees with.

    Touches no environment and does not load the catalog, so it runs against a registry too broken
    to load.
    """
    manifest = load_manifest(resolve_manifest())
    source, headers = _schema_source(manifest, args.source, args.schema)
    proposal = openapi.propose(openapi.read(source, headers), manifest.catalog_dir, source)
    label = _under(proposal.path, manifest.root)

    for name in proposal.absent:
        print(f"  {name}: declared in {label}, and this schema says nothing about it — left alone.")
    for note in proposal.drifted:
        print(f"  drifted: {note} — left alone, because that file is yours to change.")
    for name, why in proposal.skipped:
        print(f"  skipped {name}: {why}")

    if not proposal.added:
        print(f"Nothing to import — {label} already declares every type this schema describes.")
        return 0

    print(f"\n{len(proposal.added)} resource type(s) read from {source}:\n")
    names = max(len(one.name) for one in proposal.added)
    paths = max(len(one.path) for one in proposal.added)
    for one in proposal.added:
        said = f"natural_key: {openapi.key_said(one.guess.key)}" if one.guess else "no natural_key yet"
        print(f"  {one.name:<{names}}  {one.path:<{paths}}  {said}")

    print("\n" + proposal.as_diff(label).rstrip("\n"))

    if not (proposal.first or args.apply):
        print(f"\nNothing was written. Re-run with --apply to add these to {label}.")
        return 0

    try:
        proposal.path.parent.mkdir(parents=True, exist_ok=True)
        proposal.path.write_text(proposal.after, encoding="utf-8")
    except OSError as exc:
        print(f"atf: nothing written — {exc}", file=sys.stderr)
        return 2

    print(f"\nWrote {len(proposal.added)} resource type(s) to {label}.\n")
    print(NOT_INFERRED)
    return 0


def _schema_source(manifest: Any, given: str | None, named: str | None) -> tuple[str, dict[str, str]]:
    """Where the schema is, and what to send to ask for it. An argument wins over the manifest.

    Raises `ConfigError` when the manifest names no schema, or names several and `--schema` did not
    say which.
    """
    if given:
        return given, {}

    schemas = manifest.schemas
    if named is not None:
        entry = schemas.get(named)
        if entry is None:
            known = ", ".join(sorted(schemas)) or "none"
            raise ConfigError(f"no schema named {named!r} in the manifest (known: {known})")
    elif len(schemas) == 1:
        named, entry = next(iter(schemas.items()))
    elif schemas:
        raise ConfigError(
            f"the manifest names {len(schemas)} schemas ({', '.join(sorted(schemas))}) — "
            "say which one with --schema"
        )
    else:
        raise ConfigError(
            "no schema to import. Pass a path or URL, or name one in the manifest so that "
            "re-importing needs no arguments:\n\n"
            "  schemas:\n"
            "    api:\n"
            "      url: <where your service publishes its OpenAPI document>\n"
            "      headers: { Authorization: { bearer: { token_env: ATF_TOKEN } } }"
        )

    settings = resolve_env_refs(entry, f"schemas.{named}")
    url = settings.get("url")
    if isinstance(url, str) and url:
        return url, openapi.headers_for(settings)
    where = Path(str(settings.get("path"))).expanduser()
    return str(where if where.is_absolute() else manifest.root / where), {}


def _under(path: Path, root: Path) -> str:
    """A file as a reader of the suite names it, never an absolute path off this machine."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def cmd_import_run(args: argparse.Namespace) -> int:
    """Ingest a report produced by a CI run, so the cockpit knows what CI knows."""
    manifest = load_manifest(resolve_manifest())
    manifest.env(args.env)  # raises ConfigError, with the known environments, when it is not one

    store = RunStore(manifest.root)
    try:
        record = store.import_report(args.report, args.env)
    except ReportError as exc:
        print(f"atf: {exc}", file=sys.stderr)
        return 2

    counts = record.counts
    print(
        f"Imported {len(record.results)} results into {record.env}: "
        f"{counts['passed']} passed, {counts['failed']} failed, "
        f"{counts['skipped']} skipped, {counts['error']} errored."
    )
    print(f"Stored as run {record.id} in {store.dir}")
    return 0


def _subset(engine, resource_type: str | None, name: str | None) -> list[str] | None:
    if resource_type is None and name is None:
        # Ephemeral resources are built per run and torn down by the test that used them;
        # seeding them would leave orphans behind. Name one explicitly to force it.
        #
        # `data` nodes are left out for a different reason: there is nothing to seed. They are
        # observations — things a scenario looks at — and seeding one could only ever mean going
        # and looking, which `atf status` already does.
        return [
            nid
            for nid, node in engine.nodes.items()
            if not node.ephemeral and node.mode != DATA
        ]

    if resource_type is None:
        print("atf: --name needs --type", file=sys.stderr)
        return None
    if resource_type not in engine.types:
        known = ", ".join(engine.resource_types()) or "none"
        print(f"atf: unknown resource type {resource_type!r} (known: {known})", file=sys.stderr)
        return None

    matching = [
        nid
        for nid, node in engine.nodes.items()
        if node.resource == resource_type and (name is None or node.name == name)
    ]
    if not matching:
        print(f"atf: no {resource_type} named {name!r} in the catalog", file=sys.stderr)
        return None

    closure: list[str] = []
    for nid in matching:
        closure.extend(item for item in engine.closure(nid) if item not in closure)
    return closure


if __name__ == "__main__":
    raise SystemExit(main())
