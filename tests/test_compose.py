"""The guided scenario composer: what it offers, what it refuses, and what it writes."""

from __future__ import annotations

import html
import os
import re

import pytest
from fastapi.testclient import TestClient
from markupsafe import escape

from atf.cockpit.app import create_app
from atf.cockpit.deps import Cockpit, set_cockpit
from atf.discovery import parse_feature
from atf.steps import FIELD_IS, FIELD_IS_NOT
from tests.sample_project import write_sample_project

REPO_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

PREVIEW = re.compile(r'<div class="preview">(.*?)</div>', re.DOTALL)
PROVISION_PATTERN = 'the {resource_type} "{name}"'


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = write_sample_project(tmp_path / "suite")
    monkeypatch.setenv("ATF_MANIFEST", str(root / "atf.yaml"))
    monkeypatch.setenv("ATF_ENV", "dev")
    monkeypatch.setenv("PYTHONPATH", REPO_SRC)
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def client(project):
    import sys

    sys.modules.pop("suite_adapters", None)
    cockpit = Cockpit("dev")
    app = create_app(cockpit=cockpit)
    with TestClient(app) as test_client:
        test_client.cockpit = cockpit  # type: ignore[attr-defined]
        yield test_client
    set_cockpit(None)


def confirm(client) -> str:
    return client.cockpit.confirm_token


def draft(**overrides) -> dict[str, str]:
    """A complete, valid draft: one Given, one When, one Then, all from the sample project."""
    data = {
        "mode": "build",
        "feature": "Accounts",
        "title": "A brand new behaviour",
        "kw_0": "given",
        "rtype_0": "account",
        "rname_0": "primary",
        "kw_1": "when",
        "pattern_1": "I read its plan",
        "kw_2": "then",
        "pattern_2": 'the plan is "{expected}"',
        "p_2_expected": "standard",
    }
    data.update(overrides)
    return {key: value for key, value in data.items() if value is not None}


def fresh_feature(**overrides) -> dict[str, str]:
    """A draft for a brand-new feature, using only steps a module that does not exist yet can see."""
    data = {
        "mode": "build",
        "feature": "",
        "feature_title": "Billing",
        "title": "A brand new behaviour",
        "kw_0": "given",
        "rtype_0": "account",
        "rname_0": "primary",
        "kw_1": "then",
        "pattern_1": FIELD_IS,
        "p_1_resource_type": "account",
        "p_1_name": "primary",
        "p_1_field": "plan",
        "p_1_value": "standard",
    }
    data.update(overrides)
    return {key: value for key, value in data.items() if value is not None}


def esc(text: str) -> str:
    """Exactly as Jinja would have written it into the page."""
    return str(escape(text))


def preview_of(body: str) -> str:
    match = PREVIEW.search(body)
    assert match is not None, "the preview block is missing from the response"
    return html.unescape(match.group(1))


def feature_file(project, name: str = "accounts.feature"):
    return project / "specs" / "features" / name


# ---- what the picker offers -------------------------------------------------


def test_the_picker_offers_only_steps_this_suite_actually_defines(client):
    body = client.post("/compose/preview", data=draft()).text
    assert "I read its plan" in body  # a @when from the project
    assert esc('the plan is "{expected}"') in body  # a @then with a parameter
    assert "I invent a wording" not in body


# ---- a step is only offered where it can actually be used -------------------


def test_a_step_is_offered_only_where_the_binding_module_can_see_it(client):
    """pytest scopes a step to the module that declares it, so a scenario elsewhere cannot use it.

    Offering one anyway is offering a scenario that composes cleanly, saves cleanly, and then
    fails to run for a reason nothing on the page mentions.
    """
    bound = client.post("/compose/preview", data=draft(feature="Accounts")).text
    assert "I read its plan" in bound

    fresh = client.post("/compose/preview", data=draft(feature="", feature_title="Billing")).text
    assert 'data-value="I read its plan"' not in fresh, "test_accounts.py cannot reach a new module"
    # ATF's own assertions come from a plugin, so a brand-new feature can still make claims.
    assert 'data-value="node:accounts.primary"' in fresh
    # And a step chosen before the feature changed stops resolving, rather than being kept and
    # failing only when it runs.
    assert "no when step this feature can reach" in fresh


def test_a_step_that_cannot_be_reached_says_why_and_what_to_do_about_it(client):
    body = client.post("/compose/preview", data=draft(feature="", feature_title="Billing")).text
    assert "are not offered here" in body
    assert "test_accounts.py" in body
    assert "conftest.py" in body, "one of the two fixes is to move the step somewhere shared"


def test_a_step_in_a_conftest_is_reachable_from_anywhere(client, project):
    """Which is the fix the message recommends, so it had better be true."""
    (project / "specs" / "conftest.py").write_text(
        "from api import api  # noqa: F401\n"
        "from pytest_bdd import when\n\n\n"
        '@when("I do something shared")\n'
        "def _(context):\n"
        "    context.result = []\n",
        encoding="utf-8",
    )
    client.cockpit.invalidate("dev")

    fresh = client.post("/compose/preview", data=draft(feature="", feature_title="Billing")).text
    assert "I do something shared" in fresh


def test_the_generic_provisioning_step_is_never_offered_as_a_when_or_then(client):
    """It is the resource picker. Offering the same step twice teaches the wrong model."""
    steps = client.cockpit.discovery("dev").steps
    assert PROVISION_PATTERN in [step.pattern for step in steps if step.keyword == "given"]
    for keyword in ("when", "then"):
        assert PROVISION_PATTERN not in [
            step.pattern for step in client.cockpit.discovery("dev").steps_for(keyword)
        ]
    # Checked as a whole option value, not as a substring: `the result contains the {resource_type}
    # "{name}"` legitimately ends with the provisioning wording and is a different step.
    assert f'data-value="{esc(PROVISION_PATTERN)}"' not in client.get("/compose").text


def test_a_parameterised_step_of_this_suites_own_still_gets_an_input_per_capture(client):
    """Choosing one is choosing what the assertion is; it still has its own parameters to fill."""
    body = client.post("/compose/preview", data=draft()).text
    assert 'name="p_2_expected"' in body
    assert 'value="standard"' in body


def test_the_page_says_what_is_yours_to_write_by_grouping_it(client):
    """Said by the shape of the list rather than by a paragraph above it: explaining what someone
    is looking at is what you do when it is not clear enough on its own."""
    body = client.post("/compose/preview", data=draft()).text
    subject_picker = body[body.index('name="subject_2"'):]
    assert subject_picker.index("A resource") < subject_picker.index("A step this suite defines")
    assert "How a scenario is put together" not in body


def test_a_suite_with_no_when_or_then_steps_is_told_how_to_write_one(client):
    """With nothing to pick, the empty picker has to teach rather than just sit there."""
    found = client.cockpit.discovery("dev")
    found.steps = [step for step in found.steps if step.keyword == "given"]

    body = client.get("/compose").text
    assert "defines no <code>When</code> or <code>Then</code> steps yet" in body
    assert "steps/test_*.py" in body
    assert "How steps are written" in body


def test_what_needs_no_code_is_offered_apart_from_what_does(client):
    """Which is the first thing an author needs: one group needs code, the other never does."""
    body = client.post("/compose/preview", data=draft()).text
    # A When is still chosen by its wording, and this suite's are the only ones there are.
    assert "This suite&#39;s own" in body
    # A Then is chosen by what it is about, so the split there is a resource against a step.
    assert "A resource" in body and "A step this suite defines" in body


# ---- assertions built from the catalog, with no step code -------------------


def claim(**overrides) -> dict[str, str]:
    """A draft whose Then is a claim: about this resource, of that field, compared this way."""
    return draft(
        pattern_2=None,
        p_2_expected=None,
        subject_2=overrides.pop("subject", "node:accounts.primary"),
        aspect_2=overrides.pop("aspect", "plan"),
        compare_2=overrides.pop("compare", "is"),
        target_2=overrides.pop("target", "standard"),
        **overrides,
    )


# Kept under its old name so the tests that only care that *an assertion* was composed read the
# same as before.
assertion = claim


def test_an_assertion_is_four_choices_not_a_pattern_to_fill_in(client):
    """A pattern is how ATF matches a line, not how anyone thinks. What someone means is a claim:
    about this, of that, compared this way, against that."""
    body = client.post("/compose/preview", data=claim()).text
    for name in ("subject_2", "aspect_2", "compare_2", "target_2"):
        assert f'name="{name}"' in name or f'name="{name}"' in body, name
    assert ">about<" in body and ">assert<" in body and ">which must<" in body
    assert esc(FIELD_IS) not in body, "the pattern is what gets written, not what gets chosen"


def test_the_field_picker_offers_what_the_environment_holds_and_what_it_is_worth_now(client):
    body = client.post("/compose/preview", data=assertion()).text
    assert 'data-value="plan"' in body
    assert 'data-value="email"' in body
    assert "on the record in this environment" in body or "declared in the catalog" in body


def test_the_current_value_is_shown_beside_the_box_it_is_written_into(client):
    body = " ".join(client.post("/compose/preview", data=assertion(field="plan")).text.split())
    assert "<code>plan</code> is <code>standard</code> in dev right now." in body
    assert 'class="note"' in body, "the current value is an answer, not a fault"


def test_a_generic_assertion_composes_into_gherkin(client):
    body = client.post("/compose/preview", data=assertion()).text
    assert 'Then the account "primary" field "plan" is "standard"' in preview_of(body)


def test_an_assertion_about_nothing_is_held_back_before_it_is_written(client):
    body = client.post("/compose/preview", data=claim(subject="")).text
    assert "pick what this is about" in body


def test_an_assertion_shows_the_resource_it_names_with_its_status(client):
    body = client.post("/compose/preview", data=assertion()).text
    assert "accounts.primary" in body


def test_a_scenario_of_nothing_but_generic_steps_can_be_written(client, project):
    """The whole point: resources, and an assertion, with no step code anywhere."""
    data = {
        "mode": "build",
        "feature": "Accounts",
        "title": "An account carries the plan it declares",
        "confirm": confirm(client),
        "kw_0": "given",
        "rtype_0": "account",
        "rname_0": "primary",
        "kw_1": "then",
        "pattern_1": FIELD_IS,
        "p_1_resource_type": "account",
        "p_1_name": "primary",
        "p_1_field": "plan",
        "p_1_value": "standard",
    }
    response = client.post("/compose/apply", data=data)
    assert response.status_code == 200, response.text

    written = feature_file(project).read_text()
    assert 'Then the account "primary" field "plan" is "standard"' in written

    specs = parse_feature(feature_file(project), {}, set())
    assert "An account carries the plan it declares" in [spec.scenario for spec in specs]
    assert "have no definition yet" not in response.text, "a step ATF provides is already defined"


# ---- the live loop ----------------------------------------------------------


def test_the_composed_gherkin_is_read_back_by_the_same_parser(client, project):
    """The preview is not a mock-up: it is the text that will be written, and it parses."""
    engine = client.cockpit.state("dev").materializer
    body = client.post("/compose/preview", data=draft()).text

    candidate = project / "specs" / "features" / "candidate.feature"
    candidate.write_text("Feature: Accounts\n\n" + preview_of(body), encoding="utf-8")

    specs = parse_feature(candidate, engine.nodes, set(engine.types))
    assert [spec.scenario for spec in specs] == ["A brand new behaviour"]
    assert [(step.keyword, step.text) for step in specs[0].steps] == [
        ("Given", 'the account "primary"'),
        ("When", "I read its plan"),
        ("Then", 'the plan is "standard"'),
    ]
    assert specs[0].resources == ["accounts.primary"]


def test_a_repeated_keyword_is_written_as_and(client):
    body = client.post(
        "/compose/preview",
        data=draft(kw_3="given", rtype_3="project", rname_3="alpha"),
    ).text
    # The new Given lands last, so it continues the Then rather than the Given above it.
    assert 'Given the account "primary"' in preview_of(body)
    assert 'And the project "alpha"' not in preview_of(body)

    reordered = client.post(
        "/compose/preview",
        data=draft(kw_1="given", rtype_1="project", rname_1="alpha", pattern_1=None, kw_3="when",
                   pattern_3="I read its plan"),
    ).text
    assert 'And the project "alpha"' in preview_of(reordered)


def test_an_unresolved_step_is_reported_in_words(client):
    body = client.post("/compose/preview", data=draft(pattern_1="I invent a wording")).text
    assert 'class="unresolved"' in body
    assert "no when step this feature can reach is worded" in body
    assert "disabled" in body


def test_a_missing_parameter_names_the_parameter(client):
    body = client.post("/compose/preview", data=draft(p_2_expected="")).text
    assert "give a value for expected" in body


def test_a_resource_that_is_not_in_the_catalog_is_named(client):
    body = client.post("/compose/preview", data=draft(rname_0="ghost")).text
    assert "the catalog declares no account called &#39;ghost&#39;" in body


def test_a_scenario_without_a_title_says_so(client):
    body = client.post("/compose/preview", data=draft(title="")).text
    assert "The scenario needs a title" in body


def test_a_chosen_resource_carries_its_status_in_this_environment(client):
    body = client.post("/compose/preview", data=draft()).text
    assert "/catalog/node/accounts.primary?env=dev" in body
    assert "absent" in body  # nothing has been provisioned into dev yet


def test_rows_can_be_added_and_removed(client):
    added = client.post("/compose/preview", data={**draft(), "add": "then"}).text
    assert 'name="kw_3"' in added and 'value="then"' in added

    removed = client.post("/compose/preview", data={**draft(), "remove": "1"}).text
    assert 'name="kw_1"' not in removed
    assert "I read its plan" not in preview_of(removed)


def test_the_scenario_is_shown_before_anything_is_written(client, project):
    body = client.post("/compose/preview", data=draft()).text
    assert "Scenario: A brand new behaviour" in preview_of(body)
    assert "A brand new behaviour" not in feature_file(project).read_text(encoding="utf-8")


# ---- text mode --------------------------------------------------------------


def test_text_mode_starts_from_the_composed_gherkin(client):
    body = client.post("/compose/preview", data={**draft(), "to_mode": "text"}).text
    assert 'name="text"' in body
    assert 'Given the account &#34;primary&#34;' in body
    assert "Back to the builder" in body


def test_an_unfinished_row_writes_no_line_and_leaves_no_dangling_and(client):
    """A bare `Given` is not something that would ever be written, so the preview does not show one."""
    empty = client.post("/compose/preview", data={"mode": "build", "feature": "Accounts", "kw_0": "given"}).text
    assert preview_of(empty).strip() == "Scenario:"

    partial = client.post(
        "/compose/preview",
        data={
            "mode": "build",
            "feature": "Accounts",
            "title": "Half a scenario",
            "kw_0": "given",
            "kw_1": "given",
            "rtype_1": "account",
            "rname_1": "primary",
        },
    ).text
    assert 'Given the account "primary"' in preview_of(partial)
    assert "And" not in preview_of(partial)


def test_an_untitled_draft_is_never_given_an_invented_title(client):
    """A placeholder title that survived into text mode would be written to disk as the real name."""
    body = client.post("/compose/preview", data={**draft(title=""), "to_mode": "text"}).text
    assert "Untitled" not in body
    assert "The scenario needs a title" in body


def test_a_placeholder_left_in_the_text_is_not_mistaken_for_wording(client):
    typed = 'Scenario: Half done\nGiven the account "primary"\nThen the plan is "{expected}"'
    body = client.post("/compose/preview", data={"mode": "text", "feature": "Accounts", "text": typed}).text
    assert "still has a placeholder in it" in body
    assert "{expected}" in body


def test_the_text_owns_the_title_while_it_is_being_edited(client):
    typed = '  Scenario: Renamed in the text\n    Given the account "primary"\n    Then the plan is "standard"\n'
    body = client.post(
        "/compose/preview",
        data={"mode": "text", "feature": "Accounts", "title": "A stale title", "text": typed},
    ).text
    assert 'value="Renamed in the text"' in body
    assert "A stale title" not in body


def test_text_mode_is_validated_by_the_same_parser(client):
    typed = 'Scenario: Typed by hand\nGiven the account "primary"\nWhen I invent a wording\nThen the plan is "standard"'
    body = client.post("/compose/preview", data={"mode": "text", "feature": "Accounts", "text": typed}).text
    assert "No when step in this suite is worded &#39;I invent a wording&#39;" in body

    fixed = typed.replace("I invent a wording", "I read its plan")
    ok = client.post("/compose/preview", data={"mode": "text", "feature": "Accounts", "text": fixed}).text
    assert "Not ready to write yet" not in ok
    assert 'class="banner warn' not in ok, "nothing resolves badly, so nothing is said about it"


def test_typed_text_is_re_indented_to_match_the_rest_of_the_file(client, project):
    typed = (
        "Scenario Outline: Typed flat\n"
        'Given the account "<who>"\n'
        "Then the plan is \"<plan>\"\n"
        "Examples:\n"
        "| who | plan |\n"
        "| primary | standard |\n"
    )
    response = client.post(
        "/compose/apply",
        data={"mode": "text", "feature": "Accounts", "text": typed, "confirm": confirm(client)},
    )
    assert response.status_code == 200

    written = feature_file(project).read_text(encoding="utf-8")
    assert "\n  Scenario Outline: Typed flat\n" in written
    assert '\n    Given the account "<who>"\n' in written
    assert "\n    Examples:\n" in written
    assert "\n      | who | plan |\n" in written


def test_text_mode_writes_the_text_it_was_given(client, project):
    typed = "  Scenario: Typed by hand\n    Given the account \"primary\"\n    Then the plan is \"standard\"\n"
    response = client.post(
        "/compose/apply",
        data={"mode": "text", "feature": "Accounts", "text": typed, "confirm": confirm(client)},
    )
    assert response.status_code == 200
    assert "Typed by hand" in feature_file(project).read_text(encoding="utf-8")


# ---- writing ----------------------------------------------------------------


def test_appending_to_a_feature_leaves_every_other_byte_alone(client, project):
    path = feature_file(project)
    before = path.read_text(encoding="utf-8")

    response = client.post("/compose/apply", data={**draft(), "confirm": confirm(client)})
    assert response.status_code == 200

    after = path.read_text(encoding="utf-8")
    assert after.startswith(before.rstrip("\n"))
    assert after.endswith('    Then the plan is "standard"\n')

    engine = client.cockpit.state("dev").materializer
    titles = [spec.scenario for spec in parse_feature(path, engine.nodes, set(engine.types))]
    assert "A standard account reports its plan" in titles  # the file's original scenarios survive
    assert "A brand new behaviour" in titles


def test_a_new_feature_becomes_a_file_with_its_narrative(client, project):
    response = client.post(
        "/compose/apply",
        data={
            **fresh_feature(narrative="Billing follows the plan."),
            "confirm": confirm(client),
        },
    )
    assert response.status_code == 200

    written = project / "specs" / "features" / "billing.feature"
    assert written.exists()
    text = written.read_text(encoding="utf-8")
    assert text.startswith("Feature: Billing\n  Billing follows the plan.\n")
    assert "  Scenario: A brand new behaviour" in text


def test_a_write_that_would_not_parse_is_rolled_back(client, project, monkeypatch):
    """A `.feature` that does not read costs the suite every scenario in it, so this must hold."""
    from atf.cockpit.routers import compose

    path = feature_file(project)
    original = path.read_bytes()
    real = compose.parse_feature

    def blind(candidate, nodes, types):
        # Only the real file reads back as unparseable: validation against a temp copy still works,
        # so the request gets all the way to the write and has to undo it.
        return [] if candidate == path else real(candidate, nodes, types)

    monkeypatch.setattr(compose, "parse_feature", blind)

    response = client.post("/compose/apply", data={**draft(), "confirm": confirm(client)})
    assert response.status_code == 409
    assert "nothing was written" in response.text
    assert path.read_bytes() == original


def test_a_new_file_that_would_not_parse_is_not_left_behind(client, project, monkeypatch):
    from atf.cockpit.routers import compose

    written = project / "specs" / "features" / "billing.feature"
    real = compose.parse_feature
    monkeypatch.setattr(
        compose, "parse_feature", lambda p, n, t: [] if p == written else real(p, n, t)
    )

    response = client.post(
        "/compose/apply",
        data={**draft(feature="", feature_title="Billing"), "confirm": confirm(client)},
    )
    assert response.status_code == 409
    assert not written.exists()


def test_a_feature_name_carrying_a_path_is_refused(client, project):
    outside = project.parent / "escaped.feature"
    response = client.post(
        "/compose/apply",
        data={**draft(feature="", feature_title="../../escaped"), "confirm": confirm(client)},
    )
    assert response.status_code == 409
    assert "cannot contain a path" in response.text
    assert not outside.exists()
    assert list(project.parent.glob("*.feature")) == []


def test_an_unknown_feature_is_an_error_not_a_new_file(client):
    response = client.get("/compose?feature=Nope")
    assert response.status_code == 404
    assert "Nope" in response.text


def test_writing_needs_the_confirmation_token(client, project):
    response = client.post("/compose/apply", data={**draft(), "confirm": "wrong"})
    assert response.status_code == 409
    assert "must be confirmed" in response.text
    assert "A brand new behaviour" not in feature_file(project).read_text(encoding="utf-8")


def test_a_draft_that_does_not_resolve_cannot_be_written(client, project):
    response = client.post(
        "/compose/apply", data={**draft(pattern_1="I invent a wording"), "confirm": confirm(client)}
    )
    assert response.status_code == 409
    assert "not ready to write" in response.text
    assert "A brand new behaviour" not in feature_file(project).read_text(encoding="utf-8")


def test_writing_a_scenario_is_not_gated_on_mutable_envs(client, project):
    """A `.feature` file is source. The same edit is the same edit whichever environment is selected."""
    response = client.post(
        "/compose/apply?env=locked", data={**draft(), "confirm": confirm(client)}
    )
    assert response.status_code == 200
    assert "A brand new behaviour" in feature_file(project).read_text(encoding="utf-8")


# ---- after writing ---------------------------------------------------------


def test_a_scenario_in_a_bound_feature_needs_no_new_module(client):
    body = client.post("/compose/apply", data={**draft(), "confirm": confirm(client)}).text
    assert "Written to" in body
    assert "so pytest collects it" not in body, "accounts.feature is already bound"


def test_a_brand_new_feature_is_bound_without_anyone_writing_a_py_file(client, project):
    """Composing a scenario and then being told to go and write Python is the point at which the
    interface stops being one."""
    body = client.post(
        "/compose/apply", data={**fresh_feature(), "confirm": confirm(client)}
    ).text
    assert "so pytest collects it" in body
    assert "It will not run yet" not in body

    module = project / "specs" / "steps" / "test_billing.py"
    assert module.is_file()
    assert 'scenarios("../features/billing.feature")' in module.read_text()

    found = client.cockpit.discovery("dev", refresh=True)
    spec = next(item for item in found.specs if item.feature == "Billing")
    assert found.tests_for_spec(spec.id), "pytest collects it now, with nothing else written"


def test_writing_invalidates_the_cached_discovery(client):
    before = len(client.cockpit.discovery("dev").specs)
    client.post("/compose/apply", data={**draft(), "confirm": confirm(client)})
    assert len(client.cockpit.discovery("dev").specs) == before + 1


# ---- entry points -----------------------------------------------------------


def test_the_scenarios_page_offers_the_composer(client):
    assert 'href="/compose?env=dev"' in client.get("/scenarios").text


def test_a_scenario_offers_adding_another_to_the_same_feature(client):
    body = client.get("/scenarios/accounts::a-standard-account-reports-its-plan").text
    assert "/compose?env=dev&amp;feature=Accounts" in body


def test_the_composer_renders_a_whole_document_and_no_new_css(client):
    body = client.get("/compose").text
    assert "<!doctype html>" in body.lower()
    assert "<style" not in body


# ---- only the steps the scenario can actually use ---------------------------


def with_given(resource_type: str, name: str, **overrides) -> dict[str, str]:
    """A draft holding one resource, and empty When and Then rows to see what they offer."""
    data = {
        "mode": "build",
        "feature": "Accounts",
        "title": "A brand new behaviour",
        "kw_0": "given",
        "rtype_0": resource_type,
        "rname_0": name,
        "kw_1": "when",
        "kw_2": "then",
    }
    data.update(overrides)
    return {key: value for key, value in data.items() if value is not None}


def test_a_step_is_offered_only_once_the_context_holds_what_it_reads(client):
    """The reported failure: a step whose subject the scenario never provisioned composed cleanly
    and was only found out by running it."""
    holding_a_visitor = client.post("/compose/preview", data=with_given("visitor", "walkin")).text
    assert 'data-value="I list the projects of the account"' not in holding_a_visitor

    holding_an_account = client.post("/compose/preview", data=with_given("account", "primary")).text
    assert 'data-value="I list the projects of the account"' in holding_an_account


def test_asserting_on_what_a_step_produced_waits_for_a_step_that_produces(client):
    before = client.post("/compose/preview", data=with_given("account", "primary")).text
    assert 'data-value="result"' not in before

    after = client.post(
        "/compose/preview",
        data=with_given("account", "primary", pattern_1="I list the projects of the account"),
    ).text
    assert 'data-value="result"' in after
    assert "what the step before produced" in after


def test_a_catalog_resolved_assertion_never_waits_for_anything(client):
    """It reads the resource back through the adapter, so it needs nothing put on the context."""
    body = client.post("/compose/preview", data=with_given("visitor", "walkin")).text
    assert 'data-value="node:accounts.primary"' in body


def test_what_is_not_offered_is_counted_and_explained(client):
    """A hidden option is a mystery; a count and the reason is an instruction."""
    body = " ".join(client.post("/compose/preview", data=with_given("visitor", "walkin")).text.split())
    assert "not offered here: nothing above this row puts" in body
    assert "<code>account</code>" in body


def test_a_step_chosen_before_its_subject_was_removed_stops_resolving(client):
    """Otherwise removing the Given above it leaves a scenario that writes and then fails."""
    body = client.post(
        "/compose/preview",
        data=with_given("visitor", "walkin", pattern_1="I list the projects of the account"),
    ).text
    assert "nothing above this puts account on the context" in body


# ---- a Then, said as a claim -------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "written"),
    [
        ({"compare": "exists", "aspect": "", "target": ""}, 'Then the account "primary" exists'),
        ({"compare": "gone", "aspect": "", "target": ""}, 'Then the account "primary" is gone'),
        ({"compare": "is"}, 'Then the account "primary" field "plan" is "standard"'),
        ({"compare": "is-not"}, 'Then the account "primary" field "plan" is not "standard"'),
        (
            {"subject": "result", "aspect": "", "compare": "contains", "target": "node:accounts.primary"},
            'Then the result contains the account "primary"',
        ),
        (
            {"subject": "result", "aspect": "", "compare": "lacks", "target": "node:accounts.primary"},
            'Then the result does not contain the account "primary"',
        ),
    ],
)
def test_every_claim_writes_the_gherkin_it_means(client, fields, written):
    data = claim(**fields)
    if fields.get("subject") == "result":
        data["pattern_1"] = "I list the projects of the account"  # something has to produce one
    assert written in preview_of(client.post("/compose/preview", data=data).text)


def test_a_written_scenario_reads_back_into_the_same_four_choices(client):
    """The Gherkin stays the source of truth; the four boxes are a view of it, not a second copy."""
    body = client.post(
        "/compose/preview",
        data=draft(
            pattern_2=FIELD_IS_NOT,
            p_2_expected=None,
            p_2_resource_type="account",
            p_2_name="primary",
            p_2_field="plan",
            p_2_value="trial",
        ),
    ).text
    assert 'name="subject_2" value="node:accounts.primary"' in body
    assert 'name="aspect_2" value="plan"' in body
    assert 'name="compare_2" value="is-not"' in body
    assert 'name="target_2" value="trial"' in body


def test_what_can_be_claimed_depends_on_whether_a_field_was_named(client):
    about_itself = client.post("/compose/preview", data=claim(aspect="", compare="exists")).text
    picker = about_itself[about_itself.index('name="compare_2"'):]
    assert 'data-value="exists"' in picker and 'data-value="gone"' in picker
    assert 'data-value="is"' not in picker

    about_a_field = client.post("/compose/preview", data=claim()).text
    picker = about_a_field[about_a_field.index('name="compare_2"'):]
    assert 'data-value="is"' in picker and 'data-value="is-not"' in picker
    assert 'data-value="exists"' not in picker


def test_a_field_can_be_chosen_by_what_it_currently_holds(client):
    body = " ".join(client.post("/compose/preview", data=claim()).text.split())
    assert 'data-value="plan"' in body
    assert "<code>plan</code> is <code>standard</code> in dev right now." in body


def test_a_claim_composes_and_runs_without_a_line_of_step_code(client, project):
    data = {**claim(), "confirm": confirm(client)}
    del data["pattern_1"], data["kw_1"]  # no When at all: nothing is done, only read back
    response = client.post("/compose/apply", data=data)
    assert response.status_code == 200, response.text
    assert 'Then the account "primary" field "plan" is "standard"' in feature_file(project).read_text()
