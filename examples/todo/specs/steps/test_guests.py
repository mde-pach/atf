"""A feature with no step code at all — the binding is the whole module.

Both scenarios claim something about a catalog resource, so ATF's own steps cover them. What they
say it in is `specs/phrasebook.yaml`: `the guest "visitor" is ready` rather than a claim about a
`state` field, which is the shape of a record and nobody's domain language.

An ephemeral guest is read from the record this scenario built (it is never looked up, which is
what ephemeral means); a reference label is read back from the environment like anything else.
"""

from pytest_bdd import scenarios

scenarios("../features/guests.feature")
