from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from atf import providers
from atf.placeholders import Unresolved, generated, resolve

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


def test_uuid_is_different_every_time():
    made = providers.build("uuid")
    assert made.value("") != made.value("")
    assert "-" not in made.value("hex")


def test_env_reads_a_variable_and_refuses_a_missing_one(monkeypatch):
    monkeypatch.setenv("ATF_TEST_BASE", "https://example.test")
    assert providers.build("env").value("ATF_TEST_BASE") == "https://example.test"

    monkeypatch.delenv("ATF_TEST_ABSENT", raising=False)
    with pytest.raises(ValueError, match="not set in this process"):
        providers.build("env").value("ATF_TEST_ABSENT")


def test_a_missing_env_var_is_an_error_not_an_empty_string():
    """A resource created with a blank field is a resource that looks fine and is not."""
    assert "ATF_DEFINITELY_UNSET" not in os.environ
    with pytest.raises(Unresolved):
        resolve("${env:ATF_DEFINITELY_UNSET}", lookup({}))


def test_now_refuses_an_offset_it_cannot_read():
    with pytest.raises(ValueError, match="expected `now"):
        providers.build("now").value(" tomorrow")


# ---- resolving through the registry ------------------------------------------


def test_a_provider_call_resolves_through_a_placeholder(counter):
    assert resolve("${counter:a}", lookup({})) == "a-1"


def test_a_call_naming_no_provider_says_so():
    with pytest.raises(Unresolved) as err:
        resolve("${nosuchthing:x}", lookup({}))
    assert "no provider registered" in str(err.value)


def test_a_node_reference_always_wins_over_a_provider_name():
    """A registered name must never shadow the framework's own form."""
    providers.register("accounts", lambda settings: pytest.fail("a reference reached a provider"))
    try:
        assert resolve("${accounts.primary.id}", lookup({"accounts.primary": "A1"})) == "A1"
    finally:
        providers.unregister("accounts")


# ---- one evaluation per scenario ---------------------------------------------


def test_the_same_expression_twice_gives_the_same_value(counter):
    """Without this a generated value is useless in the place it is most wanted: a `When` that
    makes one and a `Then` that checks it would compare two different things."""
    memo: dict[str, object] = {}
    first = resolve("${counter:a}", lookup({}), memo)
    assert resolve("${counter:a}", lookup({}), memo) == first


def test_a_discriminator_asks_for_a_second_value(counter):
    memo: dict[str, object] = {}
    one = resolve("${counter:a}", lookup({}), memo)
    two = resolve("${counter:a#other}", lookup({}), memo)
    assert one != two


def test_a_fresh_memo_is_a_fresh_value(counter):
    """Values stand still within a scenario and must not across them."""
    assert resolve("${counter:a}", lookup({}), {}) != resolve("${counter:a}", lookup({}), {})


def test_with_no_memo_at_all_every_evaluation_is_fresh(counter):
    assert resolve("${counter:a}", lookup({})) != resolve("${counter:a}", lookup({}))


def test_a_generated_value_interpolates_into_surrounding_text(counter):
    assert resolve("name-${counter:a}-end", lookup({}), {}) == "name-a-1-end"


def test_generated_values_reach_into_nested_structures(counter):
    memo: dict[str, object] = {}
    out = resolve({"a": ["${counter:x}"], "b": {"c": "${counter:x}"}}, lookup({}), memo)
    assert out == {"a": ["x-1"], "b": {"c": "x-1"}}, "one scenario, one value"


# ---- whether a provider may key a resource ----------------------------------


@pytest.mark.parametrize("name,allowed", [("now", True), ("env", True), ("uuid", False), ("fake", False)])
def test_a_provider_says_whether_it_may_appear_in_a_natural_key(name, allowed):
    """Only the provider knows. A generator of fresh values must say no, or every run creates
    another record; a source answering from the clock or the environment can say yes."""
    assert providers.keyable(name) is allowed


def test_an_unregistered_name_is_not_refused_on_top_of_failing_to_resolve():
    assert providers.keyable("nobody-registered-this") is True


def test_the_fake_provider_is_registered_whether_or_not_faker_is_installed():
    """So the catalog can tell a value from it has no business in a key, either way."""
    assert "fake" in providers.registered()
