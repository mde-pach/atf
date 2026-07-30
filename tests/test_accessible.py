"""Reading a page the way a screen reader does: what has a role, and what is it called.

This is a decision procedure over markup — one table of "this HTML means this role and this name" —
so it is the kind of thing a unit test describes better than a scenario. What the *steps* built on
it say is in `specs/features/cockpit.feature`, against the cockpit's real pages.

The bar is not "all of ARIA". It is that the subset ATF implements is the subset a server-rendered
page uses, and that where it stops it stops predictably.
"""

from __future__ import annotations

import pytest

from atf.accessible import Page


def names(page: Page, role: str) -> list[str]:
    return [control.name for control in page.controls(role)]


# ---- what has a role ---------------------------------------------------------


@pytest.mark.parametrize(
    ("markup", "role"),
    [
        ('<a href="/x">Go</a>', "link"),
        ("<a>Go</a>", ""),  # no href: a place to jump to, not a link
        ("<button>Go</button>", "button"),
        ('<input type="submit" value="Go">', "button"),
        ('<input type="text">', "textbox"),
        ("<input>", "textbox"),  # a type nobody wrote is a text box
        ('<input type="hidden">', ""),
        ('<input type="checkbox">', "checkbox"),
        ('<input type="search">', "searchbox"),
        ("<textarea></textarea>", "textbox"),
        ("<select></select>", "combobox"),
        ("<select multiple></select>", "listbox"),
        ("<h2>Runs</h2>", "heading"),
        ("<nav></nav>", "navigation"),
        ("<li>one</li>", "listitem"),
        ("<tr></tr>", "row"),
        ('<img src="x" alt="y">', "img"),
        ("<div></div>", ""),  # a div means nothing, which is what a div is for
        ("<span></span>", ""),
    ],
)
def test_html_gives_an_element_its_role(markup, role):
    found = [control.role for control in Page(markup).controls()]
    assert (found[0] if found else "") == role


def test_a_role_said_out_loud_beats_the_one_the_tag_implies():
    """Which is the whole reason `role=` exists: the author knows what they built."""
    page = Page('<div role="alert">Saved</div><a href="/x" role="button">Go</a>')
    assert [control.role for control in page.controls()] == ["alert", "button"]


# ---- what it is called -------------------------------------------------------


def test_a_control_is_named_by_what_is_written_in_it():
    assert names(Page("<button>Save</button>"), "button") == ["Save"]


def test_aria_label_wins_over_what_is_written_in_it():
    page = Page('<button aria-label="Save this list">Save</button>')
    assert names(page, "button") == ["Save this list"]


def test_another_element_may_do_the_naming():
    page = Page('<h2 id="t">Runs</h2><section aria-labelledby="t"></section>')
    assert names(page, "region") == ["Runs"]


def test_a_field_is_named_by_its_label():
    page = Page('<label for="t">Title</label><input id="t">')
    assert names(page, "textbox") == ["Title"]


def test_a_field_wrapped_in_its_label_is_named_by_it_too():
    assert names(Page("<label>Title <input></label>"), "textbox") == ["Title"]


def test_a_field_with_no_label_falls_back_to_its_placeholder():
    """Not a good way to name a field, and still what a person sees, so it is what they will say."""
    assert names(Page('<input placeholder="Search runs">'), "textbox") == ["Search runs"]


def test_a_button_written_as_an_input_is_named_by_what_is_printed_on_it():
    page = Page('<input type="submit" value="Seed"><input type="submit">')
    assert names(page, "button") == ["Seed", "Submit"]


def test_an_image_is_named_by_its_alternative_text():
    assert names(Page('<img src="x.png" alt="lineage">'), "img") == ["lineage"]


def test_a_table_is_named_by_its_caption():
    assert names(Page("<table><caption>Instances</caption></table>"), "table") == ["Instances"]


def test_a_landmark_is_not_named_by_what_is_inside_it():
    """A `nav` around the menu is not called "Catalog Compose Runs" — it is called nothing."""
    page = Page('<nav><a href="/c">Catalog</a><a href="/r">Runs</a></nav>')
    assert names(page, "navigation") == [""]
    assert names(page, "link") == ["Catalog", "Runs"]


def test_a_decoration_the_author_hid_is_not_part_of_the_name():
    """`aria-hidden` on a glyph is the author saying "do not read this out", and it means it.

    A rail link writing an icon beside its label is called "Overview", not "◎ Overview" — and a
    reading that took the raw text would make every claim about that control wrong in a way nobody
    looking at the page could see.
    """
    page = Page('<a href="/"><span aria-hidden="true">◎</span><span>Overview</span></a>')
    assert names(page, "link") == ["Overview"]


def test_a_name_is_matched_as_a_substring_and_case_is_ignored():
    """The reading a browser gives it, so a scenario means one thing wherever it runs.

    Playwright's `get_by_role(role, name=…)` matches a substring unless told `exact=True`. Matching
    whole names here meant `the link "Scenarios" is showing` was true through the `browser` system
    and false through `html`, on the same page — which is the one thing the shared protocol exists
    to prevent. It also lets a claim name a control that carries a count inside it.
    """
    page = Page("<button>  Save   changes </button>")
    assert page.controls("button", "save changes")
    assert page.controls("button", "Save")
    assert page.controls("button", "CHANGES")
    assert not page.controls("button", "Discard")


def test_a_name_a_count_is_written_into_is_still_findable_by_the_name():
    """A rail link reads "Scenarios 7". A scenario naming the number breaks when the suite grows."""
    page = Page('<a href="/s"><span>Scenarios</span><span class="count">7</span></a>')
    assert [one.name for one in page.controls("link", "Scenarios")] == ["Scenarios 7"]


# ---- what a person can see ---------------------------------------------------


@pytest.mark.parametrize(
    "markup",
    [
        "<button hidden>Delete</button>",
        '<button aria-hidden="true">Delete</button>',
        '<button style="display: none">Delete</button>',
        '<div hidden><button>Delete</button></div>',
        "<template><button>Delete</button></template>",
    ],
)
def test_what_is_hidden_is_not_showing(markup):
    assert Page(markup).controls("button") == []


def test_disabled_is_a_thing_a_control_can_be_rather_than_a_thing_it_is_not():
    page = Page("<button disabled>Save</button><button>Cancel</button>")
    assert [(one.name, one.disabled) for one in page.controls("button")] == [("Save", True), ("Cancel", False)]


def test_aria_disabled_counts_too():
    assert Page('<button aria-disabled="true">Save</button>').controls("button")[0].disabled


# ---- what the page says ------------------------------------------------------


def test_prose_is_read_as_words_because_it_has_no_name():
    page = Page("<p>Nothing is there yet</p>")
    assert page.says("Nothing is there")
    assert not page.says("everything is there")


def test_words_nobody_can_see_are_not_showing():
    page = Page('<p hidden>Nothing is there yet</p><script>var x = "Nothing is there yet"</script>')
    assert not page.says("Nothing is there")


def test_the_title_is_the_tab_and_not_the_page():
    """So a claim about what the page *says* is never accidentally true of its title."""
    page = Page("<html><head><title>Catalog</title></head><body><p>Runs</p></body></html>")
    assert page.title == "Catalog"
    assert not page.says("Catalog")


def test_a_page_that_is_not_well_formed_is_still_read():
    """Real markup has a stray closing tag in it, and a suite is not a validator."""
    page = Page("<div><p>one</div></p><button>Save</button>")
    assert names(page, "button") == ["Save"]
    assert page.says("one")


# ---- the two systems must agree -----------------------------------------------


def test_this_reading_and_a_browser_s_agree_on_what_a_name_matches():
    """The promise of the shared protocol, checked against the other implementation of it.

    `html` and `browser` answer the same claims, so `the link "Scenarios" is showing` has to mean one
    thing through both. It did not: this matched whole names while Playwright matches substrings, so
    the same page answered differently depending on which system a suite happened to configure.
    Nothing caught it, because nothing asked them the same question.

    Skipped where there is no browser, like every other scenario that needs one.
    """
    playwright = pytest.importorskip("playwright.sync_api")
    markup = '<a href="/s"><span>Scenarios</span><span class="count">7</span></a><button>Save changes</button>'
    asked = [("link", "Scenarios"), ("link", "scenarios"), ("button", "Save"), ("button", "Discard")]

    with playwright.sync_playwright() as play:
        browser = play.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(markup)
            theirs = {(role, name): page.get_by_role(role, name=name).count() for role, name in asked}
        finally:
            browser.close()

    ours = {(role, name): len(Page(markup).controls(role, name)) for role, name in asked}
    assert ours == theirs
