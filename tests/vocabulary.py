"""One claim and one check — and **no adapter**, which is the point.

ATF ships `command`, `browser`, `filesystem` and `process`. Its own suite uses them and nothing
else, because there is no system ATF needs to test itself that ATF does not already ship. There is
no backend here and there never was.
"""

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
