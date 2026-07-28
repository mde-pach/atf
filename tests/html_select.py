"""A small CSS-subset selector over the standard library's HTML parser.

The cockpit is server-rendered: what a page shows is in the bytes it returns. So reading it needs
no browser, and this is the whole engine — a tree built by `html.parser`, and descendant chains of
simple selectors matched against it.

The supported subset is deliberately narrow, and anything outside it raises rather than quietly
matching nothing:

    tag  #id  .class  [attr]  [attr=value]        and any combination of those on one element
    a b c                                          descendant chains, whitespace-separated

No sibling or child combinators, no pseudo-classes, no comma-separated alternatives. If a
selector needs one of those, the thing being asserted on usually wants a class of its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

# Elements that never have a closing tag, so they must not be pushed onto the open-element stack.
VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
)

_SIMPLE = re.compile(
    r"^(?P<tag>[A-Za-z][\w-]*)?"
    r"(?P<marks>(?:[#.][\w-]+)*)"
    r"(?P<attrs>(?:\[[^\]]+\])*)$"
)
_ATTR = re.compile(r"\[([\w-]+)(?:=\"?([^\]\"]*)\"?)?\]")


class SelectorError(ValueError):
    """A selector using something this engine does not implement."""


@dataclass
class Element:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    parent: Element | None = None
    children: list[Element] = field(default_factory=list)
    own_text: list[str] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    @property
    def text(self) -> str:
        """Everything this element and its descendants say, as one line of collapsed whitespace."""
        parts = list(self.own_text)
        for child in self.children:
            parts.append(child.text)
        return " ".join(" ".join(parts).split())

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

    def handle_starttag(self, tag: str, attrs) -> None:
        element = Element(
            tag=tag,
            attrs={name: (value or "") for name, value in attrs},
            parent=self._current,
        )
        self._current.children.append(element)
        if tag not in VOID:
            self._open.append(element)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self._open[-1].tag == tag:
            self._open.pop()

    def handle_endtag(self, tag: str) -> None:
        # Unwind to the matching open element: a stray `</div>` must not pop the document.
        for index in range(len(self._open) - 1, 0, -1):
            if self._open[index].tag == tag:
                del self._open[index:]
                return

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._current.own_text.append(data)


def parse(markup: str) -> Element:
    builder = _Builder()
    builder.feed(markup)
    builder.close()
    return builder.root


@dataclass(frozen=True)
class Simple:
    """One element's worth of selector: a tag, ids and classes, and attribute tests."""

    tag: str = ""
    ids: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    attrs: tuple[tuple[str, str | None], ...] = ()

    def matches(self, element: Element) -> bool:
        if self.tag and element.tag != self.tag:
            return False
        if any(element.attrs.get("id") != wanted for wanted in self.ids):
            return False
        if not set(self.classes) <= element.classes:
            return False
        for name, value in self.attrs:
            if name not in element.attrs:
                return False
            if value is not None and element.attrs[name] != value:
                return False
        return True


def compile_selector(selector: str) -> list[Simple]:
    parts = selector.split()
    if not parts:
        raise SelectorError("empty selector")
    return [_simple(part) for part in parts]


def _simple(part: str) -> Simple:
    # `[attr]` tests presence; `[attr=value]` tests the value. The regex leaves group 2 as None
    # for the first and a string for the second, which is exactly the distinction.
    attrs = tuple((found.group(1), found.group(2)) for found in _ATTR.finditer(part))

    match = _SIMPLE.match(_ATTR.sub("", part))
    if match is None:
        raise SelectorError(
            f"{part!r} is not a selector this engine understands — tag, #id, .class and [attr=value] only"
        )
    marks = re.findall(r"([#.])([\w-]+)", match.group("marks") or "")
    return Simple(
        tag=(match.group("tag") or "").lower(),
        ids=tuple(name for kind, name in marks if kind == "#"),
        classes=tuple(name for kind, name in marks if kind == "."),
        attrs=attrs,
    )


def select(root: Element, selector: str) -> list[Element]:
    """Every element matching `selector`, in document order."""
    chain = compile_selector(selector)
    last = chain[-1]
    found = []
    for element in root.walk():
        if last.matches(element) and _has_ancestry(element, chain[:-1]):
            found.append(element)
    return found


def _has_ancestry(element: Element, chain: list[Simple]) -> bool:
    """Descendant matching, innermost first: each remaining part must match some ancestor."""
    remaining = list(reversed(chain))
    for ancestor in element.ancestors():
        if remaining and remaining[0].matches(ancestor):
            remaining.pop(0)
    return not remaining
