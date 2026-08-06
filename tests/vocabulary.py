"""One claim and one check — and **no adapter**, which is the point.

ATF ships `command`, `browser`, `filesystem` and `process`. Its own suite uses them and nothing
else, because there is no system ATF needs to test itself that ATF does not already ship. There is
no backend here and there never was.
"""

from pathlib import Path

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


@then('"{path}" contains "{text}"')
def _(path: str, text: str, atf) -> None:
    where = _workspace(atf) / path
    if not where.is_file():
        claims.fail(f"{path} is not there at all")
    claims.held((text in where.read_text(encoding="utf-8"), "it does not"), subject=f'"{path}"')


@then('"{path}" is not there')
def _(path: str, atf) -> None:
    claims.held((not (_workspace(atf) / path).exists(), "it is there"), subject=f'"{path}"')
