"""Sentences this suite adds to the ones ATF ships.

Nothing here is special-cased. `@act` and `@check` are the same registry the shipped words use, and
`claims` is the same library they fail through.
"""

from things import Owner

from atf import act, check, claims


@act("I list the owner\'s lists")
def _(shell, owner: Owner):
    """A kind parameter: `owner` is whatever this scenario arranged."""
    return shell(f"show {owner.email}")


@check('the listing names "{slug}"')
def _(atf, slug: str):
    claims.field_contains(atf.it(), "output", f'"{slug}"', subject="it")
