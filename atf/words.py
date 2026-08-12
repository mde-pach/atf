"""The words ATF's own suite adds — and **no system**, which is the point.

ATF ships `shell`, `browser`, `filesystem` and `process`. Its own suite uses them and nothing else,
because there is no system ATF needs to test itself that ATF does not already ship. There is no
backend here and there never was.

Two decorators. Everything below is an `@act` or a `@check`.
"""

from pathlib import Path
from typing import Any

from atf import act, check, claims


@check('it lists "{first}" before "{second}"')
def _(first, second, atf):
    """Ordering is what several scenarios check, and `contains` cannot see it."""
    result = atf.it()
    lines = str(result.get("output", "")).splitlines()
    at = {
        name: next((index for index, line in enumerate(lines) if name in line), None)
        for name in (first, second)
    }
    if None in at.values():
        return False, f'the output names neither "{first}" nor "{second}"'
    return at[first] < at[second], f'"{second}" was listed first'


def _workspace(atf, name: str = "suite") -> Path:
    """Where a scaffolded suite lives, asked of the system rather than assumed."""
    return Path(atf.ground.drivers["filesystem"].root) / name


@act('somebody changes "{path}" to "{text}"')
def _(path: str, text: str, atf) -> None:
    """A change made behind ATF's back, the way the product under test would make one."""
    where = _workspace(atf) / path
    where.parent.mkdir(parents=True, exist_ok=True)
    where.write_text(text, encoding="utf-8")


@act('somebody removes "{path}"')
def _(path: str, atf) -> None:
    (_workspace(atf) / path).unlink(missing_ok=True)


@check('"{path}" holds "{text}"')
def _(path: str, text: str, atf) -> None:
    where = _workspace(atf) / path
    if not where.is_file():
        claims.fail(f"{path} is not there at all")
    found = where.read_text(encoding="utf-8")
    return found == text, f"{path} holds {found!r}"


@check('"{path}" contains "{text}"')
def _(path: str, text: str, atf):
    where = _workspace(atf) / path
    if not where.is_file():
        claims.fail(f"{path} is not there at all")
    return text in where.read_text(encoding="utf-8"), f"{path} does not contain it"


@check('"{path}" in the {name} suite contains "{text}"')
def _(path: str, name: str, text: str, atf):
    """A file in one of the other scaffolded suites, named rather than reached through `..`."""
    where = _workspace(atf, name) / path
    if not where.is_file():
        claims.fail(f"{path} is not in the {name} suite at all")
    return text in where.read_text(encoding="utf-8"), f"{path} does not contain it"


@check('"{path}" is not there')
def _(path: str, atf):
    return not (_workspace(atf) / path).exists(), f"{path} is there"


@act('I run "{command}" against the {name} suite')
def _(command: str, name: str, atf) -> Any:
    """Run `atf` against one of the other scaffolded suites, not the one the prefix points at."""
    import subprocess

    where = _workspace(atf, name)
    finished = subprocess.run(
        ["uv", "run", "atf", *command.split()], cwd=where, capture_output=True, text=True, check=False
    )
    return {
        "command": command,
        "exit_code": finished.returncode,
        "output": finished.stdout + finished.stderr,
        "ok": finished.returncode == 0,
    }


@act('I run "{command}" in an empty directory')
def _(command: str, atf) -> Any:
    """Run `atf` somewhere with no manifest, which is what `init` is for."""
    import subprocess

    where = _workspace(atf) / "fresh"
    where.mkdir(parents=True, exist_ok=True)
    finished = subprocess.run(
        ["uv", "run", "atf", *command.split()], cwd=where, capture_output=True, text=True, check=False
    )
    return {
        "command": command,
        "exit_code": finished.returncode,
        "output": finished.stdout + finished.stderr,
        "ok": finished.returncode == 0,
    }


@act('I read "{path}" from the editor')
def _(path: str, atf) -> Any:
    """Ask the running editor for one of its answers, as data.

    The editor is a client of the same core the command is, so a scenario can claim that both say
    the same thing — which is what stops the two drifting apart.
    """
    import json
    import urllib.request

    base = atf.ground.drivers["browser"].base_url
    with urllib.request.urlopen(f"{base}{path}", timeout=10) as answer:
        return json.loads(answer.read())


@check('it says "{text}" somewhere')
def _(text: str, atf):
    """A claim over a whole answer, whatever shape it has."""
    import json

    body = json.dumps(atf.it(), default=str)
    return text in body, "it does not"
