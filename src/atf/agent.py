"""`atf edit --mcp` — the same operations, served to an agent."""

from __future__ import annotations

import json
from typing import Any

from . import commands, core
from .editor import Editor

INSTALL = "`atf edit --mcp` needs the MCP SDK: uv sync --group mcp"

#: What an agent may ask for. Each is a read of the same core the editor reads, or the one operation
#: the editor can perform — and the argument names are the command line's.
TOOLS: dict[str, dict[str, Any]] = {
    "status": {
        "description": "Where each resource stands in one environment. Never gates.",
        "arguments": {"env": "which environment", "names": "which resources, or all of them"},
    },
    "make": {
        "description": "Make each resource and everything it needs. `dry_run` says what would change.",
        "arguments": {"env": "which environment", "names": "which resources", "dry_run": "change nothing"},
    },
    "resource": {
        "description": "One resource: its declaration, what is there, what would be created or changed.",
        "arguments": {"name": "the resource"},
    },
    "impact": {
        "description": "What breaks if a resource does. Reads the graph, not history.",
        "arguments": {"name": "the resource, or nothing for the whole graph"},
    },
    "unused": {"description": "What nothing asks for.", "arguments": {}},
    "check": {"description": "Every registered check over this suite.", "arguments": {}},
    "tests": {"description": "Every behaviour the suite describes, with its verdict.", "arguments": {}},
    "graph": {"description": "Every resource, test and phrase, and the edges between them.", "arguments": {}},
    "overview": {
        "description": "Can I ship: the verdict and the four things that could contradict it.",
        "arguments": {},
    },
    "sentences": {
        "description": "Every sentence this suite can say, so an agent writes what it can run.",
        "arguments": {},
    },
    "run": {
        "description": "Run tests and record a run. `tests` names identities; without it, everything.",
        "arguments": {
            "env": "which environment",
            "tests": "which test identities, or all of them",
            "tag": "only tests carrying these tags",
            "select": "only tests naming this resource",
            "failed": "only tests whose last outcome here was failed",
        },
    },
    "docs": {
        "description": "The specs as markdown, carrying the verdict each scenario last had.",
        "arguments": {"env": "whose history supplies the verdicts", "out": "where to write"},
    },
    "compose": {
        "description": "Write a scenario as a feature file. This performs nothing — it is text.",
        "arguments": {
            "name": "the file to write under specs/",
            "scenario": "the scenario's title",
            "lines": "the sentences, each a [keyword, text] pair",
        },
    },
    "declare": {
        "description": "What declaring a resource would look like, as Python to paste. Writes nothing.",
        "arguments": {
            "kind": "the class name",
            "system": "which system it lives in",
            "unique_by": "the field, or fields, that recognise it",
            "fields": "field name to its type, as text",
            "depends_on": "the kinds it needs",
        },
    },
    "explain_failure": {
        "description": "One red test: the sentence that failed, what was wanted, what is there, and its lineage.",
        "arguments": {"test": "the test identity", "env": "whose history to read"},
    },
    "footprint": {
        "description": "What a test reads, what it writes, and what its effect nothing declares.",
        "arguments": {"test": "the test identity"},
    },
    "drift": {
        "description": "What this environment holds that no longer matches its declaration.",
        "arguments": {"env": "which environment", "names": "which resources, or all of them"},
    },
}


def answer(editor: Editor, tool: str, arguments: dict[str, Any] | None = None) -> Any:
    """Run one tool. The same call the command line makes, with the same answer."""
    given = arguments or {}
    config = str(editor.suite.manifest.path)
    editor.reload()

    if tool == "status":
        return _report(commands.status(given.get("env", ""), given.get("names") or [], manifest=editor.suite.manifest))
    if tool == "make":
        return _report(
            commands.make(
                given.get("env", ""),
                given.get("names") or [],
                dry_run=bool(given.get("dry_run")),
                manifest=editor.suite.manifest,
            )
        )
    if tool == "resource":
        return editor.resource(str(given["name"]))
    if tool == "impact":
        return commands.do_impact(str(given.get("name", "")), config=config).data
    if tool == "unused":
        return commands.do_unused(config=config).data
    if tool == "check":
        return commands.do_check(config=config).data
    if tool == "tests":
        return editor.tests()
    if tool == "graph":
        return editor.graph()
    if tool == "overview":
        return editor.overview()
    if tool == "sentences":
        return {"sentences": core.sayable(editor.suite), "subjects": core.subjects(editor.suite)}
    if tool == "run":
        from .entry import Options, do_run  # noqa: PLC0415 - one command, reached the same way

        answered = do_run(
            Options(config=config, quiet=True),
            env=str(given.get("env", "")),
            tag=tuple(given.get("tag") or ()),
            select=str(given.get("select", "")),
            failed=bool(given.get("failed")),
            keyword="",
            tests=tuple(given.get("tests") or ()),
            report=(),
            no_make=False,
            dry_run=False,
        )
        return {"code": answered.code, **answered.data}
    if tool == "docs":
        return commands.do_docs(
            out=str(given.get("out", "./atf-docs")), env=str(given.get("env", "")), config=config
        ).data
    if tool == "compose":
        path = editor.compose(
            str(given.get("name", "composed")),
            str(given.get("scenario", "a scenario")),
            [(str(one[0]), str(one[1])) for one in given.get("lines") or []],
        )
        return {"wrote": str(path)}
    if tool == "declare":
        return {"python": _declaration(given)}
    if tool == "drift":
        return commands.do_drift(str(given.get("env", "")), given.get("names") or [], config=config).data
    if tool == "footprint":
        return _footprint(editor, str(given["test"]))
    if tool == "explain_failure":
        return _explain_failure(editor, str(given["test"]), str(given.get("env", "")))
    raise KeyError(f"no tool called {tool!r} (offered: {', '.join(sorted(TOOLS))})")


def _declaration(given: dict[str, Any]) -> str:
    """A declaration written out, for an agent to read back and paste.

    Nothing is written to disk; what comes out is ordinary Python, for a person to read and paste.
    """
    kind = str(given.get("kind", "Thing"))
    system = str(given.get("system", "sql"))
    unique_by = given.get("unique_by") or ""
    fields = dict(given.get("fields") or {})
    needs = list(given.get("depends_on") or [])

    written = f"unique_by={unique_by!r}" if isinstance(unique_by, str) else f"unique_by={list(unique_by)!r}"
    if needs:
        written += f", depends_on=[{', '.join(str(one) for one in needs)}]"
    body = "\n".join(f"    {name}: {kind_of}" for name, kind_of in fields.items()) or "    pass"
    return f"@{system}({written})\nclass {kind}:\n{body}\n"


def _footprint(editor: Editor, test: str) -> dict[str, Any]:
    """What one test touches, worked out the way the run works it out."""
    from . import footprint as reach  # noqa: PLC0415

    for feature in editor.features:
        if feature.path is None:
            continue
        for scenario in feature.scenarios:
            if scenario.is_phrase:
                continue
            from .runs import identity  # noqa: PLC0415

            if identity(feature.path, scenario.name, editor.root) != test:
                continue
            found = reach.of_scenario(editor.suite, scenario, editor.phrases)
            return {
                "test": test,
                "reads": sorted(found.reads),
                "writes": sorted(found.writes),
                "opaque": list(found.opaque),
                "sealed": found.sealed,
                "why_not_sealed": found.why_not_sealed,
            }
    raise KeyError(f"no test {test!r}")


def _explain_failure(editor: Editor, test: str, env: str) -> dict[str, Any]:
    """One red test in one answer: the sentence, the record, the diff and the lineage."""
    detail = editor.test(test)
    last = detail.get("last") or {}
    where = last.get("failed_at") or {}
    holdings = []
    for name, _kind in detail.get("arranges", []):
        try:
            holdings.append(editor.resource(name))
        except Exception:  # noqa: BLE001 - a resource that will not answer is reported as unreachable
            holdings.append({"name": name, "state": "unreachable"})
    return {
        "test": test,
        "environment": env or editor.ground.config.name,
        "verdict": detail.get("verdict"),
        "flaky": detail.get("flaky"),
        "sentence": where.get("step", ""),
        "message": where.get("message", ""),
        "where": detail.get("where", ""),
        "lines": detail.get("lines", []),
        "arranged": [
            {
                "name": one.get("name"),
                "state": one.get("state"),
                "found": one.get("found"),
                "would_change": one.get("would_change"),
            }
            for one in holdings
        ],
    }


def _report(report: commands.Report) -> dict[str, Any]:
    """A command's answer as data, with `why` naming any resource that could not be made."""
    if report.error:
        return {"error": report.error, "code": report.code}
    return {
        "environment": report.env,
        "code": report.code,
        "resources": [
            {
                "name": outcome.name,
                "state": str(outcome.state),
                "did": str(outcome.did),
                "changes": sorted(outcome.changes),
                "why": outcome.why,
            }
            for outcome in report.outcomes
        ],
    }


def _server_class() -> Any:
    """The SDK's server. `mcp>=2` is what the optional group pins, so it is `MCPServer`."""
    try:
        from mcp.server.mcpserver import MCPServer  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(INSTALL) from exc
    return MCPServer


def serve(editor: Editor) -> None:
    """Serve the tools over MCP, on stdio."""
    server = _server_class()("atf")

    def register(name: str, spec: dict[str, Any]) -> None:
        def run(arguments: dict[str, Any] | None = None) -> str:
            try:
                return json.dumps(answer(editor, name, arguments), indent=2, default=str)
            except Exception as exc:  # noqa: BLE001 - an agent reads the cause, never a traceback
                return json.dumps({"error": f"{type(exc).__name__}: {exc}"})

        run.__name__ = name
        run.__doc__ = spec["description"]
        server.tool(name=name, description=spec["description"])(run)

    for name, spec in TOOLS.items():
        register(name, spec)
    server.run()
