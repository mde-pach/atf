"""`atf edit --mcp` — the same operations, served to an agent instead of to a browser.

Every tool here is a call into [core](core.py) or [commands](commands.py), which is the same rule
the editor follows: **no privileged path.** An agent gets the answers the command line gives, in the
shape the editor reads, and nothing that only an agent can do.

What that buys is stated in each reference page's *To an agent* face, and it comes down to one
thing: **an agent gets a cause, not a stack trace.** When a resource cannot be made the reason is a
field — immutable environment, `require`, `observe`, unreachable system — so an agent branches on it
rather than parsing prose.

The MCP SDK is not a dependency of ATF. A framework should not decide that every suite serves
agents, so the command says what to install rather than failing on an import nobody asked for.
"""

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
    raise KeyError(f"no tool called {tool!r} (offered: {', '.join(sorted(TOOLS))})")


def _report(report: commands.Report) -> dict[str, Any]:
    """A command's answer as data.

    **When a resource cannot be made, the reason is a field** — immutable environment, `require`,
    `observe`, or an unreachable system. An agent branches on it rather than reading prose.
    """
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
