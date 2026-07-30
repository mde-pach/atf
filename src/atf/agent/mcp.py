"""ATF over MCP: the same closed vocabulary the composer runs on, offered to an agent."""

from __future__ import annotations

import contextlib
import importlib
from dataclasses import dataclass
from typing import Any

from .. import __version__
from ..session import Session
from .introspect import Composition, Surface, compose, describe, try_scenario

# The module the server class lives in. Named here, once, so an SDK that moves it fails here.
SDK_MODULE = "mcp.server.mcpserver"
SDK_CLASS = "MCPServer"

INSTALL = "uv sync --group mcp"

# Where the endpoint sits on the cockpit's own server: one process serves both views of one suite.
MOUNT = "/mcp"


def unavailable() -> str:
    """Why MCP cannot be served here — `""` when it can.

    Answered by importing, not by checking a version: the question is whether this will work, and
    the only honest way to know is to do the thing that would fail.
    """
    try:
        importlib.import_module(SDK_MODULE)
    except ImportError:
        return f"the MCP SDK is not installed — `{INSTALL}`"
    return ""


# ---- the three verbs, bound to one suite ------------------------------------


@dataclass
class Tools:
    """The three tools, over one session.

    Every answer is about an environment, and a session is what holds one — its catalog, its
    discovery and its status, cached and shared with the cockpit's pages. So an agent and a person
    looking at the same suite see the same thing, including how stale it is.
    """

    session: Session

    # ---- what can be said here ------------------------------------------------

    def describe(self, environment: str = "", feature: str = "") -> dict[str, Any]:
        """Everything a scenario in this suite may say.

        The steps this suite defines with what each captures, needs and produces; the catalog's
        resources with where each stands in this environment right now and what fields it is known
        to have; the phrases this suite writes and what they stand for; the closed list of
        comparisons and of `#markers`; and the resource types with the actions declared on them.

        Read this first. Everything `compose` will accept is in here, and nothing else is.
        """
        env = self._env(environment)
        return {
            "environments": self.session.environments.names,
            "mutable": self.session.is_mutable(env),
            **describe(self._surface(env), feature),
        }

    # ---- these choices, and the Gherkin they mean -----------------------------

    def compose(
        self,
        title: str,
        rows: list[dict[str, Any]],
        feature: str = "",
        environment: str = "",
    ) -> dict[str, Any]:
        """Turn a list of chosen rows into the scenario they mean, without writing anything.

        Each row is a mapping with a `keyword` of `given`, `when` or `then`.

        A `given` names a resource: `{"keyword": "given", "resource_type": ..., "resource_name": ...}`
        — both from `describe`'s `resources`.

        A `when` or a `then` is either a step said by its wording —
        `{"keyword": "when", "pattern": ..., "params": {...}}`, the pattern and its captures from
        `describe`'s `steps` — or a `then` said as a claim:
        `{"keyword": "then", "subject": "node:<id>", "aspect": "<field>", "compare": "<key>",
        "target": "<value>"}`, where the compare key comes from `describe`'s `comparisons`.

        What comes back is the Gherkin, and `problems`: one sentence per thing standing between
        these choices and a scenario — a step this feature cannot reach, a resource the catalog does
        not declare, a claim about a slot nothing above it produced. A composition with no problems
        is one that will run.
        """
        env = self._env(environment)
        return _as_answer(compose(self._surface(env), rows, title, feature))

    # ---- run one -------------------------------------------------------------

    def run(
        self,
        scenario: str = "",
        title: str = "",
        rows: list[dict[str, Any]] | None = None,
        feature: str = "",
        environment: str = "",
    ) -> dict[str, Any]:
        """Run a scenario this suite already has, or a draft that has not been written yet.

        Name a `scenario` — an id from `describe`'s features, or the scenario's own title — to run
        what is already there. Give `rows` and a `title` instead to run a draft: it is written to a
        scratch feature, run, and taken away again, so the answer arrives before the decision to
        keep it does.

        Running provisions, so this is refused where the environment is not in `mutable_envs`.
        """
        env = self._env(environment)
        if not self.session.is_mutable(env):
            return {
                "ran": False,
                "problems": [
                    f"{env} is read-only — add it to `mutable_envs` in atf.yaml to let ATF change it."
                ],
            }
        if scenario:
            return self._run_saved(scenario, env)

        drafted = compose(self._surface(env), rows or [], title, feature)
        if not drafted.ready:
            return {"ran": False, **_as_answer(drafted)}
        trial = try_scenario(self._surface(env), drafted.gherkin, feature, feature or title)
        return {
            "ran": True,
            "gherkin": drafted.gherkin,
            "outcome": trial.outcome,
            "passed": trial.passed,
            "failed_at": trial.step,
            "detail": trial.detail,
            "seconds": round(trial.duration, 3),
        }

    def _run_saved(self, scenario: str, env: str) -> dict[str, Any]:
        found = self.session.discovery.of(env)
        spec = found.spec(scenario) or next(
            (one for one in found.specs if one.scenario == scenario), None
        )
        if spec is None:
            known = ", ".join(sorted(one.id for one in found.specs)) or "none"
            return {"ran": False, "problems": [f"no scenario {scenario!r} here (this suite has {known})"]}

        tests = found.tests_for_spec(spec.id)
        if not tests:
            return {
                "ran": False,
                "problems": [
                    f"{spec.id} is written but nothing collects it, so pytest has no test to run. "
                    f'Bind its feature with scenarios("…") in a steps/test_*.py module.'
                ],
            }
        summary = self.session.jobs.run_now([test.nodeid for test in tests], env)
        return {
            "ran": True,
            "scenario": spec.id,
            "counts": summary.counts,
            "results": [
                {
                    "test": nodeid,
                    "outcome": result.outcome,
                    "failed_at": (
                        f"{result.failed_step.keyword} {result.failed_step.text}".strip()
                        if result.failed_step
                        else ""
                    ),
                    "detail": result.detail,
                    "seconds": round(result.duration, 3),
                }
                for nodeid, result in sorted(summary.results.items())
            ],
        }

    # ---- what every answer is about -------------------------------------------

    def _env(self, environment: str) -> str:
        """Which environment a call is about. An unknown name is refused, never quietly replaced.

        The same rule the cockpit holds to: silently answering about dev when someone asked about
        staging is how an agent ends up acting on the wrong place.
        """
        if not environment:
            return self.session.default_env
        if environment not in self.session.manifest.environments:
            known = ", ".join(self.session.environments.names)
            raise ValueError(f"unknown environment {environment!r} — this suite has {known}")
        return environment

    def _surface(self, env: str) -> Surface:
        return Surface(
            env=env,
            root=self.session.manifest.root,
            specs_dir=self.session.manifest.specs_dir,
            engine=self.session.state(env).materializer,
            found=self.session.discovery.of(env),
            status=self.session.status.of(env),
        )


def _as_answer(drafted: Composition) -> dict[str, Any]:
    return {
        "title": drafted.title,
        "gherkin": drafted.gherkin,
        "ready": drafted.ready,
        "problems": drafted.problems,
        "steps": [
            {"keyword": row.shown_keyword, "text": row.text, "problem": row.problem}
            for row in drafted.rows
        ],
    }


# ---- the server ---------------------------------------------------------------


def server(session: Session) -> Any:
    """An MCP server offering the three tools over this suite.

    The tools are registered from the bound methods above, so their descriptions are the docstrings
    a reader of this file sees and their argument schemas are the signatures — there is no second
    copy of either to fall out of step with the first.
    """
    reason = unavailable()
    if reason:
        raise RuntimeError(reason)

    made = getattr(importlib.import_module(SDK_MODULE), SDK_CLASS)
    built = made(
        name="atf",
        version=__version__,
        instructions=(
            "This suite describes real systems. Call `describe` first: it lists every step, "
            "resource, phrase, comparison and marker a scenario here may use. Compose only from "
            "what it lists — anything else is refused with the reason. `compose` turns choices into "
            "Gherkin without writing it; `run` runs a scenario or a draft."
        ),
    )
    tools = Tools(session)
    for tool in (tools.describe, tools.compose, tools.run):
        built.add_tool(tool, name=tool.__name__)
    return built


def endpoint(session: Session, host: str = "127.0.0.1") -> tuple[Any, Any]:
    """The application to mount at `MOUNT`, and the lifespan it needs, for one suite.

    Two things, and the caller wires each where it belongs: a mounted sub-application's lifespan is
    *not* run by its parent, so mounting alone leaves the session manager unstarted until the first
    call fails.

    `host` reaches the SDK, which refuses a request whose `Host` header names somewhere else — the
    check that keeps a page in a browser from reaching an agent's endpoint by guessing its address.
    """
    built = server(session)
    # Stateless: the cockpit is single-user and localhost by default, and nothing here outlives a
    # call, so there is no session to resume and no state to expire.
    served = built.streamable_http_app(
        streamable_http_path="/", stateless_http=True, json_response=True, host=host
    )

    @contextlib.asynccontextmanager
    async def lifespan(_: Any) -> Any:
        async with built.session_manager.run():
            yield

    return served, lifespan
