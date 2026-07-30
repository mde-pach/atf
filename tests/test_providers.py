"""The provider registry, where no scenario can watch.

What a provider *produces* is now said in `specs/features/providers.feature` — a generated value
that is the same twice in one scenario and different when asked for a second, a timestamp that
reaches the backend, a variable nobody exported stopping a seed and naming itself. Those are things
a person can watch a command do.

What is left is the registry: how a provider is registered, how an expression splits into a name and
an argument, and which providers may appear in a natural key. Nothing a suite does observes any of
it except by having providers at all.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from atf.model import providers
from atf.model.placeholders import generated, resolve

LOOKUP = dict.get


def lookup(known: dict[str, object]):
    return lambda nid: known.get(nid)


@pytest.fixture
def counter():
    """A provider of ATF's own, registered the way a project would register one."""

    class Counter:
        def __init__(self, settings=None):
            self.n = 0

        def value(self, argument):
            self.n += 1
            return f"{argument or 'n'}-{self.n}"

    providers.register("counter", Counter)
    yield
    providers.unregister("counter")


# ---- the registry ------------------------------------------------------------


def test_a_provider_is_registered_and_built_like_an_adapter(counter):
    assert "counter" in providers.registered()
    assert providers.build("counter").value("x") == "x-1"

def test_an_unregistered_name_says_which_ones_there_are():
    with pytest.raises(providers.UnknownProvider) as err:
        providers.build("nope")
    assert "no provider registered as 'nope'" in str(err.value)
    assert "now" in str(err.value)

def test_settings_reach_the_provider():
    made = providers.build("now", {"at": datetime(2020, 1, 1, tzinfo=UTC)})
    assert made.value("+0d 00:00") == "2020-01-01T00:00:00Z"


# ---- how an expression is read ----------------------------------------------


@pytest.mark.parametrize(
    "expression,name,argument",
    [
        ("fake:email", "fake", "email"),
        ("uuid", "uuid", ""),
        ("now+1d 09:00", "now", "+1d 09:00"),
        ("now-2d 18:30", "now", "-2d 18:30"),
        ("env:BASE_URL", "env", "BASE_URL"),
        # The discriminator tells two calls apart and must never reach the provider.
        ("fake:company#new", "fake", "company"),
        ("uuid#second", "uuid", ""),
    ],
)

def test_an_expression_splits_into_a_name_and_an_argument(expression, name, argument):
    assert providers.split(expression) == (name, argument)

def test_something_that_is_not_a_call_at_all_names_nothing():
    assert providers.split("!!") == ("", "")

def test_a_node_reference_is_not_a_provider_call():
    assert generated("accounts.primary.id") is False
    assert generated("fake:email") is True


# ---- the providers ATF ships -------------------------------------------------

def test_a_node_reference_always_wins_over_a_provider_name():
    """A registered name must never shadow the framework's own form."""
    providers.register("accounts", lambda settings: pytest.fail("a reference reached a provider"))
    try:
        assert resolve("${accounts.primary.id}", lookup({"accounts.primary": "A1"})) == "A1"
    finally:
        providers.unregister("accounts")


# ---- what may be part of an identity -----------------------------------------


@pytest.mark.parametrize(
    ("name", "allowed"),
    [("now", True), ("env", True), ("uuid", False), ("fake", False)],
)
def test_a_provider_says_whether_it_may_appear_in_a_natural_key(name, allowed):
    """Only the provider knows. A generator of fresh values must say no, or every run creates
    another record; a source answering from the clock or the environment can say yes."""
    assert providers.keyable(name) is allowed


def test_the_fake_provider_is_registered_whether_or_not_faker_is_installed():
    """So the catalog can tell a value from it has no business in a key, either way."""
    assert "fake" in providers.registered()

def test_with_no_memo_at_all_every_evaluation_is_fresh(counter):
    assert resolve("${counter:a}", lookup({})) != resolve("${counter:a}", lookup({}))
