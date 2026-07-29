"""What is on a page, from the HTML it sent — by role and accessible name, never by selector.

A server-rendered page says what it is in the bytes it returns. Reading it therefore needs no
browser, and a suite that reads it this way still says what it means:

```gherkin
Then the heading "Catalog" is showing
And the link "Compose" is showing
```

**Why not a selector.** `table.instances tbody tr` describes today's markup: rename the class and
every scenario that mentioned it is wrong about a page that still works perfectly. A role and an
accessible name describe the *thing* — what a screen reader announces, and what a person means when
they say "the Save button". A suite written in them survives a redesign and fails a regression,
which is the right way round.

**Why not only a browser.** ATF's `browser` adapter answers the same questions against a page that
has actually run, and it must exist for the claims no amount of parsing can make — a stylesheet
applied, a fragment swapped in, a combobox opened. But it needs a browser installed, and most of
what a suite claims about a server-rendered interface is true of the response itself. This is that
half, and it costs nothing.

**What is implemented is a subset of ARIA, and it says so.** The roles below are the implicit ones
HTML gives an element, with an explicit `role=` always winning; the name is computed in the order
the accessible name specification gives, stopping at the first that answers. What is deliberately
not here: anything needing layout (a thing scrolled out of view is still showing to this module),
CSS from a stylesheet (only an inline `display:none` hides), and roles nothing renders. A page whose
name computation this cannot follow is a page to look at with the `browser` adapter instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from typing_extensions import override

# Elements that never have a closing tag, so they must not be pushed onto the open-element stack.
VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
)

# Subtrees that say nothing to a reader. `title` is the tab's name, not the page's content, and
# `template` is markup held back for later — neither is on the page.
UNSPOKEN = frozenset({"script", "style", "head", "template", "title", "noscript"})

# The implicit role of an element, where HTML gives it one. An explicit `role=` always wins, and a
# tag missing here has no role — which is right for `div` and `span`, whose whole purpose is to
# carry no meaning.
IMPLICIT: dict[str, str] = {
    "article": "article",
    "aside": "complementary",
    "button": "button",
    "dialog": "dialog",
    "fieldset": "group",
    "figure": "figure",
    "footer": "contentinfo",
    "form": "form",
    "h1": "heading",
    "h2": "heading",
    "h3": "heading",
    "h4": "heading",
    "h5": "heading",
    "h6": "heading",
    "header": "banner",
    "hr": "separator",
    "img": "img",
    "li": "listitem",
    "main": "main",
    "nav": "navigation",
    "ol": "list",
    "option": "option",
    "output": "status",
    "progress": "progressbar",
    "section": "region",
    "summary": "button",
    "table": "table",
    "tbody": "rowgroup",
    "td": "cell",
    "textarea": "textbox",
    "tfoot": "rowgroup",
    "th": "columnheader",
    "thead": "rowgroup",
    "tr": "row",
    "ul": "list",
}

# What an `<input>` is, which is the one tag whose role is a matter of its `type`. A type not here
# has no role — `hidden` most of all, which is the point.
INPUT_ROLES: dict[str, str] = {
    "": "textbox",
    "button": "button",
    "checkbox": "checkbox",
    "email": "textbox",
    "image": "button",
    "number": "spinbutton",
    "radio": "radio",
    "range": "slider",
    "reset": "button",
    "search": "searchbox",
    "submit": "button",
    "tel": "textbox",
    "text": "textbox",
    "url": "textbox",
}

# Controls whose name is what a person types into or beside, rather than what they read inside.
# A `<label>` names these; everything else is named by its own text.
LABELLED = frozenset({"input", "select", "textarea"})

# The roles whose name *is* what is written in them. The distinction matters: a `nav` wrapping the
# whole menu is not called "Catalog Compose Runs", it is called nothing at all unless somebody named
# it. Landmarks and containers are named only by `aria-label`, `aria-labelledby` or `title`, which
# is what stops `the region "…"` from matching whatever happens to be inside one today.
NAME_FROM_CONTENT = frozenset(
    {
        "button",
        "cell",
        "checkbox",
        "columnheader",
        "heading",
        "link",
        "listitem",
        "menuitem",
        "option",
        "radio",
        "row",
        "rowheader",
        "switch",
        "tab",
        "tooltip",
        "treeitem",
    }
)

_HIDDEN_STYLE = re.compile(r"(display\s*:\s*none|visibility\s*:\s*hidden)", re.IGNORECASE)


@dataclass(frozen=True)
class Control:
    """One thing on a page, said the way a person says it.

    What every reading of an interface comes back as, whichever adapter did the reading — so a
    claim means the same thing against a page a server sent and a page a browser ran.
    """

    role: str
    name: str
    text: str = ""
    disabled: bool = False


@dataclass
class Element:
    """One element of the page, and where it sits."""

    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    parent: Element | None = None
    children: list[Element] = field(default_factory=list)
    own_text: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """Everything this element and its descendants say, as one line of collapsed whitespace."""
        return " ".join(self._spoken().split())

    def _spoken(self) -> str:
        if self.tag in UNSPOKEN:
            return ""
        parts = list(self.own_text)
        parts.extend(child._spoken() for child in self.children)
        return " ".join(parts)

    def walk(self):
        for child in self.children:
            yield child
            yield from child.walk()

    def ancestors(self):
        current = self.parent
        while current is not None:
            yield current
            current = current.parent


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element(tag="#document")
        self._open = [self.root]

    @property
    def _current(self) -> Element:
        return self._open[-1]

    @override
    def handle_starttag(self, tag: str, attrs) -> None:
        element = Element(
            tag=tag,
            attrs={name: (value or "") for name, value in attrs},
            parent=self._current,
        )
        self._current.children.append(element)
        if tag not in VOID:
            self._open.append(element)

    @override
    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self._open[-1].tag == tag:
            self._open.pop()

    @override
    def handle_endtag(self, tag: str) -> None:
        # Unwind to the matching open element: a stray `</div>` must not pop the document.
        for index in range(len(self._open) - 1, 0, -1):
            if self._open[index].tag == tag:
                del self._open[index:]
                return

    @override
    def handle_data(self, data: str) -> None:
        if data.strip():
            self._current.own_text.append(data)


class Page:
    """A parsed page, ready to be asked what is on it."""

    def __init__(self, markup: str) -> None:
        builder = _Builder()
        builder.feed(markup)
        builder.close()
        self.root = builder.root
        # Every element carrying an id, for `aria-labelledby` and `<label for=…>` to reach. Built
        # once, because a name computation that walked the document per control would be quadratic.
        self.by_id: dict[str, Element] = {}
        self.labels: dict[str, list[Element]] = {}
        for element in self.root.walk():
            if (found := element.attrs.get("id")) and found not in self.by_id:
                self.by_id[found] = element
            if element.tag == "label" and (whose := element.attrs.get("for")):
                self.labels.setdefault(whose, []).append(element)

    @property
    def title(self) -> str:
        for element in self.root.walk():
            if element.tag == "title":
                return " ".join(" ".join(element.own_text).split())
        return ""

    # ---- what is on it ------------------------------------------------------

    def controls(self, role: str = "", name: str = "") -> list[Control]:
        """Everything showing with this role, and this accessible name where one is given.

        A name is matched whole, case-insensitively, with whitespace collapsed — the same reading
        `get_by_role` gives it in a browser, so a scenario means one thing in both places.
        """
        wanted = _flat(name)
        found = []
        for element in self.root.walk():
            its_role = self.role_of(element)
            if not its_role or (role and its_role != role):
                continue
            if self.hidden(element):
                continue
            its_name = self.name_of(element)
            if wanted and _flat(its_name) != wanted:
                continue
            found.append(
                Control(
                    role=its_role,
                    name=its_name,
                    text=element.text,
                    disabled=self.disabled(element),
                )
            )
        return found

    def says(self, text: str) -> bool:
        """Whether these words are readable anywhere a person can see them.

        Prose has no accessible name — ARIA computes one for things you can act on, and a paragraph
        is not one — so this is the claim about what a page *says*, and it is still not a selector.
        """
        return _flat(text) in _flat(self._visible_text(self.root))

    def _visible_text(self, element: Element) -> str:
        if element.tag in UNSPOKEN or (element is not self.root and self.hidden(element, deep=False)):
            return ""
        parts = list(element.own_text)
        parts.extend(self._visible_text(child) for child in element.children)
        return " ".join(parts)

    # ---- what one element is ------------------------------------------------

    def role_of(self, element: Element) -> str:
        """This element's role: what it says it is, else what HTML makes it."""
        if declared := element.attrs.get("role", "").split():
            return declared[0]
        if element.tag == "a":
            return "link" if "href" in element.attrs else ""
        if element.tag == "input":
            return INPUT_ROLES.get(element.attrs.get("type", "").lower(), "")
        if element.tag == "select":
            multiple = "multiple" in element.attrs or element.attrs.get("size", "1") not in ("", "1")
            return "listbox" if multiple else "combobox"
        return IMPLICIT.get(element.tag, "")

    def name_of(self, element: Element) -> str:
        """This element's accessible name, by the first of the rules that answers.

        The order is the specification's, cut to what a server-rendered page uses: what another
        element is said to name it, what it says its own name is, what HTML names it natively, and
        the advisory `title` as a last resort.
        """
        if labelledby := element.attrs.get("aria-labelledby", "").split():
            named = [self.by_id[ref].text for ref in labelledby if ref in self.by_id]
            if any(named):
                return " ".join(part for part in named if part)
        if labelled := element.attrs.get("aria-label", "").strip():
            return labelled
        if native := self._native_name(element, self.role_of(element)):
            return native
        return element.attrs.get("title", "").strip()

    def _native_name(self, element: Element, role: str) -> str:
        if element.tag == "img":
            return element.attrs.get("alt", "").strip()
        if element.tag == "table":
            caption = next((one for one in element.children if one.tag == "caption"), None)
            return caption.text if caption else ""
        if element.tag == "input" and element.attrs.get("type", "").lower() in ("button", "submit", "reset"):
            # A button written as an input is named by what is printed on it, and a submit with
            # nothing printed on it still reads "Submit" — which is what the browser draws.
            return element.attrs.get("value", "").strip() or _DEFAULT_VALUES.get(
                element.attrs.get("type", "").lower(), ""
            )
        if element.tag in LABELLED:
            return self._label_for(element)
        return element.text if role in NAME_FROM_CONTENT else ""

    def _label_for(self, element: Element) -> str:
        """What names a field: a label pointing at it, a label around it, or its placeholder."""
        for label in self.labels.get(element.attrs.get("id", ""), []):
            if label.text:
                return label.text
        for ancestor in element.ancestors():
            if ancestor.tag == "label" and ancestor.text:
                return ancestor.text
        return element.attrs.get("placeholder", "").strip()

    def hidden(self, element: Element, *, deep: bool = True) -> bool:
        """Whether a person can see it. Its own markup, and its ancestors' when asked deeply."""
        chain = [element, *element.ancestors()] if deep else [element]
        for one in chain:
            if one.tag in UNSPOKEN:
                return True
            if "hidden" in one.attrs or one.attrs.get("aria-hidden", "").lower() == "true":
                return True
            if _HIDDEN_STYLE.search(one.attrs.get("style", "")):
                return True
        return False

    def disabled(self, element: Element) -> bool:
        return "disabled" in element.attrs or element.attrs.get("aria-disabled", "").lower() == "true"


# What a browser prints on a button with nothing written on it.
_DEFAULT_VALUES = {"submit": "Submit", "reset": "Reset"}


def _flat(text: str) -> str:
    """A name as it is compared: whitespace collapsed, case ignored."""
    return " ".join(text.split()).casefold()
