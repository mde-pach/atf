"""The scenario surface, which must resolve `owner: Owner` to what the scenario arranged."""

from __future__ import annotations

from pytest_bdd import scenarios

scenarios("features/one_owner.feature")
