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
    body = client.get("/compose").text
    assert "I read its plan" in body  # a @when from the project
    assert esc('the plan is "{expected}"') in body  # a @then with a parameter
    assert "I invent a wording" not in body


def test_the_generic_provisioning_step_is_never_offered_as_a_when_or_then(client):
    """It is the resource picker. Offering the same step twice teaches the wrong model."""
    steps = client.cockpit.discovery("dev").steps
    assert PROVISION_PATTERN in [step.pattern for step in steps if step.keyword == "given"]
    for keyword in ("when", "then"):
        assert PROVISION_PATTERN not in [
            step.pattern for step in client.cockpit.discovery("dev").steps_for(keyword)
        ]
    assert esc(PROVISION_PATTERN) not in client.get("/compose").text


def test_a_parameterised_step_gets_an_input_per_capture(client):
    body = client.post("/compose/preview", data=draft()).text
    assert 'name="p_2_expected"' in body
    assert 'value="standard"' in body


def test_the_page_explains_which_steps_are_yours_to_write(client):
    body = client.get("/compose").text
    assert "You never write these" in body
    assert "@when" in body and "@then" in body
    assert "scenarios(…)" in body  # the second half of the work, said before it is needed


def test_a_suite_with_no_when_or_then_steps_is_told_how_to_write_one(client):
    """With nothing to pick, the empty picker has to teach rather than just sit there."""
    found = client.cockpit.discovery("dev")
    found.steps = [step for step in found.steps if step.keyword == "given"]

    body = client.get("/compose").text
    assert "defines no <code>When</code> or <code>Then</code> steps yet" in body
    assert "steps/test_*.py" in body
    assert "How steps are written" in body


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
    assert "nothing in this suite defines a when step worded" in body
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


def test_the_diff_is_shown_before_anything_is_written(client, project):
    body = client.post("/compose/preview", data=draft()).text
    assert 'class="diff"' in body
    assert '<div class="add">+  Scenario: A brand new behaviour</div>' in body
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
    assert "Every step resolves" in ok


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
            **draft(feature="", feature_title="Billing", narrative="Billing follows the plan."),
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


def test_a_scenario_in_a_bound_feature_is_reported_as_runnable(client):
    body = client.post("/compose/apply", data={**draft(), "confirm": confirm(client)}).text
    assert "still parses" in body
    assert "runnable now" in body
    assert "It will not run yet" not in body


def test_a_brand_new_feature_says_it_needs_a_scenarios_binding(client):
    body = client.post(
        "/compose/apply",
        data={**draft(feature="", feature_title="Billing"), "confirm": confirm(client)},
    ).text
    assert "It will not run yet" in body
    assert "No test collects Billing yet" in body
    assert "../features/billing.feature" in body


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
