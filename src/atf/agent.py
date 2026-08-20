"""`atf edit --mcp` — the same operations, served to an agent."""

from __future__ import annotations

import json
from typing import Any

from . import commands, core
from .editor import Editor

INSTALL = "`atf edit --mcp` needs the MCP SDK: uv sync --group mcp"

#: What an agent may ask for. **The six commands, and the reads the editor makes** — the argument
#: names are the command line's, so an agent that can read the help can drive this.
TOOLS: dict[str, dict[str, Any]] = {
    "plan": {
        "description": "Is this suite sound, and what will happen? Lint, standing, drift, undeclared.",
        "arguments": {"env": "which environment", "apply": "make what is missing, and run nothing"},
    },
    "run": {
        "description": "Run tests and record a run. `tests` names identities; without it, everything.",
        "arguments": {
            "env": "which environment",
            "tests": "which test identities, or all of them",
            "tag": "only scenarios carrying these tags",
            "select": "only scenarios reaching this thing, kind, system, phrase or file",
            "failed": "only tests whose last outcome here was failed",
            "accept": "draft the claims for scenarios that promise none",
        },
    },
    "explain": {
        "description": "Everything about one thing: a thing, a kind, a system, a scenario, a phrase, a file.",
        "arguments": {
            "pointed_at": "what to explain, or nothing for the shape of the suite",
            "env": "which environment",
        },
    },
    "resource": {
        "description": "One thing: its declaration, what is there, what would be created or changed.",
        "arguments": {"name": "the thing"},
    },
    "tests": {"description": "Every behaviour the suite describes, with its verdict.", "arguments": {}},
    "graph": {"description": "Every thing, test and phrase, and the edges between them.", "arguments": {}},
    "overview": {
        "description": "Can I ship: the verdict and the four things that could contradict it.",
        "arguments": {},
    },
    "sentences": {
        "description": "Every sentence this suite can say, so an agent writes what it can run.",
        "arguments": {},
    },
    "compose": {
        "description": "Write a scenario as a feature file. This performs nothing — it is text.",
        "arguments": {
            "name": "the file to write in the suite",
            "scenario": "the scenario's title",
            "lines": "the sentences, each a [keyword, text] pair",
        },
    },
    "declare": {
        "description": "What declaring a thing would look like, as Python to paste. Writes nothing.",
        "arguments": {
            "kind": "the class name",
            "system": "which system it lives in",
            "fields": "field name to its type, as text",
            "needs": "field name to what fills it when nobody gives one",
        },
    },
    "explain_failure": {
        "description": "One red test: the sentence that failed, what was wanted, what is there, and its lineage.",
        "arguments": {"test": "the test identity", "env": "whose history to read"},
    },
    "footprint": {
        "description": "What a test reads, what it writes, and which of its sentences declare no effect.",
        "arguments": {"test": "the test identity"},
    },
}


def answer(editor: Editor, tool: str, arguments: dict[str, Any] | None = None) -> Any:
    """Run one tool. The same call the command line makes, with the same answer."""
    given = arguments or {}
    config = str(editor.suite.manifest.path)
    editor.reload()

    if tool == "plan":
        return commands.do_plan(
            str(given.get("env", "")), apply=bool(given.get("apply")), config=config
        ).data
    if tool == "explain":
        return commands.do_explain(
            str(given.get("pointed_at", "")), str(given.get("env", "")), config=config
        ).data
    if tool == "resource":
        return editor.resource(str(given["name"]))
    if tool == "tests":
        return editor.tests()
    if tool == "graph":
        return editor.graph()
    if tool == "overview":
        return editor.overview()
    if tool == "sentences":
        return {"sentences": core.sayable(), "subjects": core.subjects(editor.suite)}
    if tool == "run":
        from .entry import (
            Options,
            do_run,
        )

        answered = do_run(
            Options(config=config, quiet=True),
            env=str(given.get("env", "")),
            tag=tuple(given.get("tag") or ()),
            select=str(given.get("select", "")),
            failed=bool(given.get("failed")),
            accept=bool(given.get("accept")),
            contract=False,
            keyword="",
            tests=tuple(given.get("tests") or ()),
            report=(),
            import_="",
            format_="ctrf",
            no_make=False,
            dry_run=False,
            jobs="1",
        )
        return {"code": answered.code, **(answered.data or {})}
    if tool == "compose":
        path = editor.compose(
            str(given.get("name", "composed")),
            str(given.get("scenario", "a scenario")),
            [(str(one[0]), str(one[1])) for one in given.get("lines") or []],
        )
        return {"wrote": str(path)}
    if tool == "declare":
        return {"python": _declaration(given)}
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
    system = str(given.get("system", "sql.row"))
    fields = dict(given.get("fields") or {})
    needs = dict(given.get("needs") or {})

    lines = []
    for name, written in fields.items():
        filled = needs.get(name)
        lines.append(f"    {name}: {written} = needs({filled})" if filled else f"    {name}: {written}")
    body = "\n".join(lines) or "    pass"
    return f"@{system}()\nclass {kind}:\n{body}\n"


def _footprint(editor: Editor, test: str) -> dict[str, Any]:
    """What one test touches, worked out the way the run works it out."""
    from . import footprint as reach

    for feature in editor.features:
        if feature.path is None:
            continue
        for scenario in feature.tests:
            from .runs import identity

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


def _server_class() -> Any:
    """The SDK's server. `mcp>=2` is what the optional group pins, so it is `MCPServer`."""
    try:
        from mcp.server.mcpserver import MCPServer
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
