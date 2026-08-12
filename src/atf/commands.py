"""The six subcommands — init, plan, run, enter, explain, edit — and what each one answers."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import enter as entering
from . import explain as explaining
from . import plan as planning
from . import reconcile, runs, scaffold
from .environment import Ground, GroundError, build_ground
from .loader import Suite, SuiteError, load_suite
from .manifest import Manifest, ManifestError, load
from .spi import State

OK, FAILED, NEVER_STARTED = 0, 1, 2

#: The stable machine names `--json` puts on stderr for anything that exits `2`.
UNREACHABLE = "environment_unreachable"
INVALID = "suite_invalid"
NOT_OURS = "environment_not_ours"
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
                print(
                    json.dumps({"error": {"code": self.error_code or USAGE, "message": self.error}}),
                    file=sys.stderr,
                )
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


# --- Reading the suite --------------------------------------------------------------------------


@dataclass
class Read:
    """A suite and its words, read once. What every command below starts from."""

    manifest: Manifest
    suite: Suite
    features: list[Any]
    phrases: dict[str, Any]
    ground: Ground | None = None
    #: Why there is no ground, where there is none. A command that can still answer, answers.
    why: str = ""


def read(config: str | None, env: str = "", *, needs_ground: bool = True) -> Read:
    """Read the suite, then try for the environment — the suite first, always.

    An environment that will not build is carried on `Read.why`; the suite is still read.
    """
    from . import lives
    from . import phrases as phrase_reader
    from .feature import read_all

    manifest = load(Path(config)) if config else load()
    suite = load_suite(manifest)
    features = read_all(manifest.specs)
    phrases = phrase_reader.collect(features)
    lives.remember(lives.read(suite, features, phrases))

    ground, why = None, ""
    try:
        ground = build_ground(suite, env)
    except (GroundError, ManifestError) as exc:
        why = str(exc)
        if needs_ground:
            raise
    return Read(manifest=manifest, suite=suite, features=features, phrases=phrases, ground=ground, why=why)


def _environment(reading: Read, env: str) -> str:
    return reading.ground.config.name if reading.ground else (env or reading.manifest.default_env)


# --- init ---------------------------------------------------------------------------------------


def do_init(*, env: str = "local", force: bool = False, run_it: bool = True) -> Answer:
    """Scaffold a suite that **ends green against the real system**.

    The first five minutes are the entire adoption decision, and handing somebody an empty file
    spends them asking the newcomer to do the hard part first, alone, before anything has worked.
    So this looks around for what is already there, declares what it finds, writes one scenario,
    runs it, and prints green.
    """
    here = Path.cwd()
    try:
        found = scaffold.look_around(here)
        written = scaffold.init(here, env=env, force=force, found=found)
    except FileExistsError as exc:
        return Answer(code=FAILED, error=str(exc).replace(f"{here}/", ""), error_code=USAGE)
    except OSError as exc:
        return fault(str(exc))

    lines = [f"found {one}" for one in found.notes]
    lines += [f"wrote {path.relative_to(here)}" for path in written]
    green, said = (scaffold.first_run(here) if run_it else (True, []))
    lines += said
    return Answer(
        code=OK if green else FAILED,
        lines=lines,
        data={"written": [str(path) for path in written], "found": found.notes, "green": green},
    )


# --- plan ---------------------------------------------------------------------------------------


def do_plan(
    env: str = "",
    names: list[str] | None = None,
    *,
    apply: bool = False,
    lives_too: bool = False,
    config: str | None = None,
) -> Answer:
    """Is this suite sound, and what will happen? Absorbs status, drift, adopt and check."""
    try:
        reading = read(config, env, needs_ground=False)
    except (ManifestError, SuiteError) as exc:
        return fault(str(exc), INVALID)

    environment = _environment(reading, env)
    built = planning.build(
        reading.suite, reading.features, reading.phrases, reading.ground, environment, names or []
    )
    if reading.why and not built.unreachable:
        built.unreachable = reading.why

    lines = planning.lines(built)
    if lives_too:
        lines += ["", "  how long each thing lives", *planning.spans_lines(built, reading.suite)]

    if apply:
        if reading.ground is None:
            return fault(reading.why or f"{environment} could not be built", UNREACHABLE)
        if not reading.ground.mutable:
            return fault(
                f"{environment} is not ATF's to make things in — it is owned by them. "
                f"Point at one ATF owns, or set `owner: atf` on it.",
                NOT_OURS,
            )
        done = planning.apply(reading.ground, reading.suite, names or [])
        lines += ["", "  applied"]
        lines += [f"    {one.name:<24} {one.did}" for one in done]

    return Answer(
        code=OK if built.sound else FAILED,
        lines=lines,
        data=planning.as_json(built, reading.manifest.root),
    )


# --- explain ------------------------------------------------------------------------------------


def do_explain(pointed_at: str = "", env: str = "", *, config: str | None = None) -> Answer:
    """Tell me everything about this. Absorbs impact, unused, why-red and history."""
    try:
        reading = read(config, env, needs_ground=False)
    except (ManifestError, SuiteError) as exc:
        return fault(str(exc), INVALID)

    environment = _environment(reading, env)
    root = reading.manifest.root
    if not pointed_at:
        return Answer(
            lines=explaining.summary(
                reading.suite, reading.features, reading.phrases, reading.ground, root, environment
            ),
            data={
                "scenarios": sum(len(one.tests) for one in reading.features),
                "things": sorted(reading.suite.instances),
                "unused": explaining.loose(reading.suite, reading.features, reading.phrases),
            },
        )

    try:
        subject = explaining.about(
            reading.suite,
            reading.features,
            reading.phrases,
            reading.ground,
            root,
            environment,
            pointed_at,
        )
    except explaining.Unknown as exc:
        return fault(str(exc), USAGE)
    return Answer(
        lines=subject.lines,
        data={
            "what": subject.what,
            "name": subject.name,
            "tests": subject.tests,
            "resources": subject.resources,
        },
    )


# --- enter --------------------------------------------------------------------------------------


def do_enter(
    scenario: str = "", env: str = "", *, config: str | None = None, typed: list[str] | None = None
) -> Answer:
    """Put me inside this failure. With no argument: the thing that just broke."""
    try:
        reading = read(config, env)
    except (ManifestError, SuiteError, GroundError) as exc:
        return fault(str(exc), INVALID)

    environment = _environment(reading, env)
    assert reading.ground is not None  # `read` raises where there is none, so there is one here
    try:
        wanted = scenario or entering.last_failure(reading.manifest.root, environment)
        session = entering.open_on(
            reading.suite, reading.ground, reading.features, reading.phrases, wanted
        )
    except entering.NoFailure as exc:
        return fault(str(exc), USAGE)

    try:
        for line in entering.header(session):
            print(line)
        entering.replay(session)
        _prompt(session, typed)
    finally:
        entering.close(session)
    return Answer(lines=[], data={"scenario": session.name})


def _prompt(session: entering.Session, typed: list[str] | None) -> None:
    """The prompt. Reads a line, runs it, and says what `it` became."""
    scripted = list(typed or [])
    while True:
        if scripted:
            line = scripted.pop(0)
            print(f"{entering.PROMPT}{line}")
        else:
            try:
                line = input(f"\n{entering.PROMPT}").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
        if line in (entering.DONE, "exit", "quit"):
            return
        if line in ("?", "help"):
            for one in entering.help_lines():
                print(one)
        elif line == entering.NEXT:
            entering.step(session)
        elif line.startswith(entering.KEEP):
            title = line[len(entering.KEEP) :].strip().strip('"')
            written = entering.keep(session, title or session.name)
            if session.scenario.path is not None:
                entering.append(Path(session.scenario.path), written)
                print(f"  kept in {session.scenario.path}")
            else:
                print(written)
        else:
            entering.say(session, line)


# --- edit ---------------------------------------------------------------------------------------


def do_edit(env: str, port: int, *, config: str | None = None) -> Answer:
    """Let me look around. Absorbs `docs`: what it renders is what the editor serves."""
    from .editor import serve

    serve(Path(config) if config else None, env, port)
    return Answer()


def do_render(*, out: str = "./atf-docs", env: str = "", config: str | None = None) -> Answer:
    """The suite's own spec, written out. `atf edit --write` — the same pages, on disk for CI."""
    from . import rendering

    try:
        reading = read(config, env, needs_ground=False)
    except (ManifestError, SuiteError) as exc:
        return fault(str(exc), INVALID)
    environment = _environment(reading, env)
    try:
        written = rendering.write(reading.suite, reading.features, Path(out), environment)
    except OSError as exc:
        return fault(str(exc), USAGE)
    return Answer(
        lines=[rendering.summary(entry) for entry in written] or ["no scenarios to render"],
        data={"pages": [{"path": str(path), "scenarios": total} for path, total, _ in written]},
    )


# --- Shared -------------------------------------------------------------------------------------


def standing(env: str = "", names: list[str] | None = None, *, config: str | None = None) -> Any:
    """Where each thing stands. The editor and an agent read this; no command prints it alone."""
    reading = read(config, env)
    assert reading.ground is not None
    wanted = planning._selected(reading.suite, names or [])
    return reconcile.status(reading.ground, wanted)


def verdict_of(past: list[runs.Run]) -> Any:
    return runs.verdict(outcome.outcome for run in past for outcome in run.outcomes)


def unreachable_in(outcomes: list[Any]) -> bool:
    return any(one.state is State.UNREACHABLE for one in outcomes)
