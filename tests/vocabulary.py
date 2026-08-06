"""One claim and one check — and **no adapter**, which is the point.

ATF ships `command`, `browser`, `filesystem` and `process`. Its own suite uses them and nothing
else, because there is no system ATF needs to test itself that ATF does not already ship. There is
no backend here and there never was.
"""

from atf import check, claim

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
