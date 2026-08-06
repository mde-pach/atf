"""The sentences this prototype needs, registered through ATF's own registry."""

from __future__ import annotations

from typing import Any

import pytest
from atf_registry import given, then
from resources import Owner


@given('the {kind} "{name}"', target_fixture="arranged")
def _(kind: str, name: str, request: pytest.FixtureRequest) -> Any:
    """`Given the owner "primary"` — arranging is asking for that instance's fixture."""
    return request.getfixturevalue(name)


@then('the owner in scope is "{email}"')
def _(owner: Owner, email: str) -> None:
    """A step taking `owner: Owner` is handed whatever the scenario arranged."""
    assert owner.email == email, f"expected {email}, got {owner.email}"
