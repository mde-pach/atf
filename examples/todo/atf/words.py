"""The sentences this suite adds, and the two formats it can write a run in."""

from atf import act, check, claims, kind, report


@act('I ask for the lists of "{name}"')
def _(name, http, atf):
    """Whatever an act returns becomes `it`, and the sentence after reads it."""
    owner = atf.look_up("owner", name)
    return http.client.get(f"/owners/{owner['id']}/lists").json()


@check('the answer names "{slug}"')
def _(atf, slug: str):
    """A claim in the domain's words, failing through the library the shipped ones use."""
    named = [one.get("slug") for one in atf.it().get("items", [])]
    claims.held((slug in named, f"it named {', '.join(named) or 'nothing'}"), subject="the answer")


@kind("slug")
def _(value):
    """Lower case, digits and hyphens. A shape, where the value is not the point."""
    text = str(value)
    return bool(text) and all(one.isdigit() or one.islower() or one == "-" for one in text), (
        f"{value!r} is not a slug"
    )


@report("tally")
def _(run, path):
    """A line per test, which is the shortest thing a format can be."""
    lines = [f"{one.outcome} {one.test}" for one in run.outcomes]
    path.write_text(f"{run.environment}\n" + "\n".join(lines) + "\n", encoding="utf-8")
