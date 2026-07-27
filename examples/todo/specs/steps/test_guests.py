"""A feature with no step code at all — the binding is the whole module.

Both scenarios assert on fields of catalog resources, so ATF's own steps cover them. An ephemeral
guest is read from the record this scenario built (it is never looked up, which is what ephemeral
means); a reference label is read back from the environment like anything else.
"""

from pytest_bdd import scenarios

scenarios("../features/guests.feature")
