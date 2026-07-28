"""The `atf` command: init, serve, seed, status, run, lint, import-run."""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path
from typing import Any

from .bootstrap import bootstrap
from .catalog import CatalogError
from .config import ConfigError, load_manifest, resolve_manifest
from .lint import check as lint_specs
from .lint import report as lint_report
from .materializer import BLOCKED, CREATED, EPHEMERAL, PRESENT, REFERENCE
from .runner import ERROR, FAILED
from .runner import run as run_tests
from .scaffold import scaffold
from .store import ReportError, RunStore

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
    except (ConfigError, CatalogError) as exc:
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
    run.set_defaults(handler=cmd_run)

    lint = sub.add_parser("lint", help="check that no spec line says something only the layer below should know")
    lint.set_defaults(handler=cmd_lint)

    imported = sub.add_parser("import-run", help="record a pytest --json-report file from CI as a run")
    imported.add_argument("env")
    imported.add_argument("report", type=Path)
    imported.set_defaults(handler=cmd_import_run)

    return parser


# ---- commands --------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    written = scaffold(root, root.name)

    if not written:
        print(f"{root} already contains a suite — nothing written.")
        return 0
    print(f"Scaffolded an ATF suite in {root}:")
    for path in written:
        print(f"  {path.relative_to(root)}")
    print("\nNext: `atf run` — it passes as it stands, against a stand-in backend. Then `atf serve`.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .cockpit.app import create_app

    manifest = load_manifest(resolve_manifest())
    app = create_app(args.env)
    url = f"http://{args.host}:{args.port}"
    print(BANNER.format(url=url, host=args.host, mutable=", ".join(sorted(manifest.mutable_envs)) or "none"))
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

    for result in outcome["results"]:
        action = str(result["action"])
        mark = "ok" if result["ok"] else ("skip" if action == BLOCKED else "FAIL")
        detail = f" — {result['detail']}" if result.get("detail") else ""
        print(f"  [{mark:>4}] {result['id']:<40} {action}{detail}")

    print("\n" + _tally(outcome["results"]) + f" in {boot.env}.")
    if not args.keep_going and any(not result["ok"] for result in outcome["results"]):
        remaining = len(subset) - len(outcome["results"])
        if remaining > 0:
            print(f"Stopped at the first failure; {remaining} resource(s) not attempted. "
                  "Re-run with --keep-going to attempt independent ones.")
    return 1 if any(not result["ok"] for result in outcome["results"]) else 0


def _tally(results: list[dict[str, Any]]) -> str:
    """A failure counts as failed whatever it was attempting."""
    counts = {"created": 0, "already present": 0, "found": 0, "failed": 0, "blocked": 0}
    for result in results:
        action = str(result["action"])
        if not result["ok"]:
            counts["blocked" if action == BLOCKED else "failed"] += 1
        elif action == CREATED:
            counts["created"] += 1
        elif action == REFERENCE:
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
        detail = f" — {entry['detail']}" if entry.get("detail") else ""
        print(f"  {nid:<{width}}  {entry['status']:<12}{detail}")

    present = sum(1 for entry in status.values() if entry["status"] == PRESENT)
    ephemeral = sum(1 for entry in status.values() if entry["status"] == EPHEMERAL)
    total = len(status) - ephemeral
    print(f"\n{present}/{total} present in {boot.env}" + (f" ({ephemeral} built per run)" if ephemeral else ""))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    boot = bootstrap(args.env)
    summary = run_tests(args.paths or None, boot.env, boot.manifest.root, boot.manifest.specs_dir)
    # History is a convenience, not the point of the command: a read-only checkout still runs.
    with contextlib.suppress(OSError):
        RunStore(boot.manifest.root).save(summary.as_record(boot.env))

    for nodeid, result in sorted(summary.results.items()):
        print(f"  [{result.outcome:>7}] {nodeid}  {result.duration:.2f}s")
        if result.outcome not in {FAILED, ERROR}:
            continue
        step = result.failed_step
        if step is not None:
            print(f"           at: {step.keyword} {step.text}".rstrip())
        if result.detail:
            print(f"           {result.detail.splitlines()[-1]}")

    counts = summary.counts
    print(
        f"\n{counts['passed']} passed, {counts['failed']} failed, "
        f"{counts['skipped']} skipped, {counts['error']} errored in {boot.env}"
    )
    if not summary.results and summary.returncode != 0:
        print(summary.output, file=sys.stderr)
    return 0 if summary.returncode == 0 else 1


def cmd_lint(args: argparse.Namespace) -> int:
    """A spec line may not name a field, a selector, a status code, a path or a CLI flag.

    Reads the feature files and nothing else: no environment, no adapters, no collection. It is a
    check on what a reader reads, so it must run in a checkout with no backend anywhere near it.
    """
    manifest = load_manifest(resolve_manifest())
    findings = lint_specs(manifest.specs_dir)
    print(lint_report(findings, manifest.specs_dir), file=sys.stderr if findings else sys.stdout)
    return 1 if findings else 0


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
        return [nid for nid, node in engine.nodes.items() if node["lifecycle"] != EPHEMERAL]

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
        if node["resource"] == resource_type and (name is None or node["name"] == name)
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
