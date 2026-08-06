"""One claim and one check — and **no adapter**, which is the point.

ATF ships `command`, `browser`, `filesystem` and `process`. Its own suite uses them and nothing
else, because there is no system ATF needs to test itself that ATF does not already ship. There is
no backend here and there never was.
"""

import re
import shlex
from pathlib import Path
from typing import Any

from atf import check, claim, claims, then, when

SUBCOMMANDS = {"init", "status", "make", "run", "check", "docs", "edit", "impact", "unused"}


@claim('the {result} lists "{first}" before "{second}"')
def _(result, first, second):
    """Ordering is what these scenarios check, and `contains` cannot see it.

    A claim rather than a marker because it is about a record — the whole of one result slot — and
    not about a value.
    """
    lines = result["output"].splitlines()
    at = {
        name: next((index for index, line in enumerate(lines) if name in line), None)
        for name in (first, second)
    }
    if None in at.values():
        return False, f'the output names neither "{first}" nor "{second}"'
    return at[first] < at[second], f'"{second}" was listed first'


@check("every scenario names the subcommand it exercises")
def _(suite):
    """ATF's own convention, enforced by the same `atf check` that enforces anybody's."""
    for scenario in suite.scenarios:
        if not SUBCOMMANDS & set(scenario.tags):
            yield scenario, f"no subcommand tag; expected one of {', '.join(sorted(SUBCOMMANDS))}"


@check("every atf command the documentation shows exists, with the flags it shows")
def _(suite):
    """A page showing a command nobody can run is a page that was true once.

    Only the command and its flags, never the output: most blocks are written against the todo
    suite in the documentation and cannot run here. This is the half that can be checked from a
    cold start, and it is the half that goes stale.
    """
    from atf.entry import cli

    globals_ = _flags_of(cli)
    for where, line in _shell_lines(_pages(suite)):
        for fragment in re.split(r"&&|\|\|", line):
            words = _invocation(shlex.split(fragment.strip()))
            if not words:
                continue
            name = next((word for word in words[1:] if not word.startswith("-")), "")
            if name and name not in cli.commands:
                yield where, f"no `atf {name}` command: {fragment.strip()}"
                continue
            known = globals_ | (_flags_of(cli.commands[name]) if name else set())
            for word in words[1:]:
                flag = word.split("=", 1)[0]
                if flag.startswith("-") and flag not in known:
                    yield where, f"`atf {name or ''}` has no {flag}: {fragment.strip()}"


@check("every name the documentation imports from atf is exported by atf")
def _(suite):
    """`from atf import report` was in the reference for as long as it did not work."""
    import atf

    for where, line in _lines(_pages(suite), r"^\s*from atf import (.+)$"):
        for name in (part.strip() for part in line.split(",")):
            if name and name not in atf.__all__:
                yield where, f"`atf` exports no {name!r}"


def _invocation(words: list[str]) -> list[str]:
    """The `atf …` part of a command line, past whatever runs it. Empty where it runs something else."""
    while words and words[0] in ("uv", "run", "--project", "exec") or (words and words[0].startswith("/")):
        words = words[1:]
    return words if words[:1] == ["atf"] else []


def _pages(suite) -> list[Path]:
    """Every page of the documentation, and the README, which is one too."""
    root = suite.suite.manifest.root
    return sorted(root.glob("*.md")) + sorted((root / "docs").rglob("*.md"))


def _lines(pages: list[Path], pattern: str) -> list[tuple[str, str]]:
    found = []
    for page in pages:
        for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            match = re.match(pattern, line)
            if match:
                found.append((f"{page.name}:{number}", match.group(1)))
    return found


def _shell_lines(pages: list[Path]) -> list[tuple[str, str]]:
    """Every command the documentation shows, and nothing it shows as output.

    In a `console` block only a `$ ` line is a command and the rest is what came back; in an `sh`
    block every line is one. A `text` block is output throughout.
    """
    found = []
    for page in pages:
        language = ""
        for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            if line.startswith("```"):
                language = "" if language else (line[3:].strip() or "plain")
                continue
            said = line.strip()
            if language == "console" and said.startswith("$ "):
                found.append((f"{page.name}:{number}", said[2:]))
            elif language in ("sh", "bash") and said and not said.startswith("#"):
                found.append((f"{page.name}:{number}", said))
    return found


def _flags_of(command) -> set[str]:
    return {one for parameter in command.params for one in getattr(parameter, "opts", [])}


def _workspace(atf) -> Path:
    """Where the scaffolded suite lives, asked of the adapter rather than assumed."""
    return Path(atf.ground.adapters["filesystem"].root) / "suite"


@when('somebody changes "{path}" to "{text}"')
def _(path: str, text: str, atf) -> None:
    """A change made behind ATF's back, the way the product under test would make one."""
    where = _workspace(atf) / path
    where.parent.mkdir(parents=True, exist_ok=True)
    where.write_text(text.replace("\\n", "\n"), encoding="utf-8")


@when('somebody removes "{path}"')
def _(path: str, atf) -> None:
    (_workspace(atf) / path).unlink(missing_ok=True)


@then('"{path}" holds "{text}"')
def _(path: str, text: str, atf) -> None:
    where = _workspace(atf) / path
    if not where.is_file():
        claims.fail(f"{path} is not there at all")
    found = where.read_text(encoding="utf-8")
    claims.held((found == text.replace("\\n", "\n"), f"it holds {found!r}"), subject=f'"{path}"')


@when('I run "{command}" in an empty directory')
def _(command: str, atf) -> Any:
    """Run `atf` somewhere with no manifest, which is what `init` is for.

    The directory is inside the workspace, so it is taken away with everything else.
    """
    import subprocess  # noqa: PLC0415

    where = _workspace(atf) / "fresh"
    where.mkdir(parents=True, exist_ok=True)
    finished = subprocess.run(  # noqa: S603
        ["uv", "run", "atf", *command.split()], cwd=where, capture_output=True, text=True, check=False
    )
    return atf.remember("result", {
        "command": command,
        "exit_code": finished.returncode,
        "output": finished.stdout + finished.stderr,
        "ok": finished.returncode == 0,
    })


@when('I read "{path}" from the editor')
def _(path: str, atf) -> Any:
    """Ask the running editor for one of its answers, as data.

    The editor is a client of the same core the command is, so a scenario can claim that both say
    the same thing — which is what stops the two drifting apart.
    """
    import json  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    base = atf.ground.adapters["browser"].base_url
    with urllib.request.urlopen(f"{base}{path}", timeout=10) as answer:  # noqa: S310
        return atf.remember("answer", json.loads(answer.read()))


@then('the answer contains "{text}"')
def _(text: str, atf) -> None:
    import json  # noqa: PLC0415

    body = json.dumps(atf.recall("answer"), default=str)
    claims.held((text in body, "it does not"), subject="the editor's answer")


@then('"{path}" contains "{text}"')
def _(path: str, text: str, atf) -> None:
    where = _workspace(atf) / path
    if not where.is_file():
        claims.fail(f"{path} is not there at all")
    claims.held((text in where.read_text(encoding="utf-8"), "it does not"), subject=f'"{path}"')


@then('"{path}" is not there')
def _(path: str, atf) -> None:
    claims.held((not (_workspace(atf) / path).exists(), "it is there"), subject=f'"{path}"')
