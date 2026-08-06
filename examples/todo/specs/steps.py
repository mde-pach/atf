"""Sentences this suite adds to the ones ATF ships.

Nothing here is special-cased. `@when` and `@then` are the same registry the built-ins use, and
`claims` is the same library they fail through — so a step written here fails as well as one of
ATF's own does.
"""

from resources import Owner

from atf import claims, then, when


@when("I list the owner's lists", target="result")
def _(shell, owner: Owner):
    """A kind parameter: `owner` is whatever this scenario arranged."""
    return shell(f"show {owner.email}")


@then('the listing names "{slug}"')
def _(atf, slug: str):
    claims.field_contains(atf.recall("result"), "output", slug, subject="the result")
