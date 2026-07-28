"""The selector engine behind this suite's `element` adapter.

It lives here rather than in `src/atf/`, because a client for one system is exactly what the
framework must not contain. It is tested directly because the cockpit scenarios only exercise it as
deep as their own claims go, and the matching is fiddly enough to be worth pinning down.
"""

from __future__ import annotations

import html_select
import pytest

MARKUP = """
<!doctype html>
<html>
  <head><title>Catalog · ATF</title></head>
  <body>
    <div id="main" class="stack">
      <table class="records instances">
        <thead><tr><th>instance</th><th>status</th></tr></thead>
        <tbody>
          <tr class="known"><td>primary</td><td class="state">present</td></tr>
          <tr class="known"><td>secondary</td><td class="state">absent</td></tr>
          <tr class="divider"><td colspan="2">in dev, not declared</td></tr>
        </tbody>
      </table>
      <form id="compose-form">
        <button class="primary" type="button">Write this <em>scenario</em></button>
        <input name="title" value="x">
        <br>
      </form>
    </div>
  </body>
</html>
"""


@pytest.fixture
def document():
    return html_select.parse(MARKUP)


def select(document, selector):
    return html_select.select(document, selector)


# ---- the shapes a selector can take -----------------------------------------


def test_a_tag_matches_every_element_of_that_tag(document):
    assert len(select(document, "tr")) == 4  # one header row and three body rows


def test_a_class_matches_elements_carrying_it(document):
    assert len(select(document, ".known")) == 2


def test_several_classes_must_all_be_present(document):
    assert len(select(document, "table.records.instances")) == 1
    assert select(document, "table.records.missing") == []


def test_an_id_matches_one_element(document):
    found = select(document, "#compose-form")
    assert len(found) == 1 and found[0].tag == "form"


def test_a_tag_and_a_class_together(document):
    assert len(select(document, "td.state")) == 2


def test_an_attribute_can_be_tested_for_presence_or_value(document):
    assert len(select(document, "[colspan]")) == 1
    assert len(select(document, "button[type=button]")) == 1
    assert select(document, "button[type=submit]") == []


def test_a_descendant_chain_needs_every_ancestor_in_order(document):
    assert len(select(document, "table.instances tbody tr")) == 3
    assert len(select(document, "form#compose-form button.primary")) == 1
    # `tbody` is inside `table`, not the other way round.
    assert select(document, "tbody table tr") == []


def test_a_chain_matches_through_intermediate_elements(document):
    """Descendant, not child: `#main tr` holds even though rows are two levels down."""
    assert len(select(document, "#main tr")) == 4


def test_a_selector_this_engine_does_not_implement_is_refused(document):
    for selector in ("div > p", "li:first-child", "a + b"):
        with pytest.raises(html_select.SelectorError):
            select(document, selector)


def test_an_empty_selector_is_refused(document):
    with pytest.raises(html_select.SelectorError):
        select(document, "   ")


# ---- what a matched element says --------------------------------------------


def test_text_gathers_descendants_and_collapses_whitespace(document):
    button = select(document, "button.primary")[0]
    assert button.text == "Write this scenario"


def test_attributes_are_carried_verbatim(document):
    button = select(document, "button.primary")[0]
    assert button.attrs["type"] == "button"
    assert button.classes == {"primary"}


def test_matches_come_back_in_document_order(document):
    rows = select(document, "tbody tr")
    assert [row.attrs.get("class") for row in rows] == ["known", "known", "divider"]


# ---- parsing oddities --------------------------------------------------------


def test_a_void_element_does_not_swallow_what_follows(document):
    """`<br>` has no closing tag; pushing it would nest the rest of the form inside it."""
    assert len(select(document, "form input")) == 1
    assert len(select(document, "input br")) == 0


def test_a_stray_closing_tag_does_not_unwind_the_document():
    document = html_select.parse("<div class=a><p>one</p></span><p>two</p></div>")
    assert len(select(document, "div.a p")) == 2


def test_an_empty_document_matches_nothing():
    assert select(html_select.parse(""), "div") == []
