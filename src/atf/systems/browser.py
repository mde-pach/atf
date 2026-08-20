"""The `browser` driver, and `Page` — a page opened in it and looked at by role."""

from __future__ import annotations

from typing import Any, TypedDict

from typing_extensions import override

from .. import claims
from ..declare import Driver, DriverProperty, Resource, Unreachable, declaration_of, register_system
from ..spi import Payload
from ..steps import act, check


class Browser(Driver):
    """One browser, and the pages opened in it.

    A step asks for this by the name `browser`; `Page` works through it as `self.browser`.
    """

    class Settings(TypedDict, total=False):
        """What an environment configures."""

        base_url: str
        headless: bool

    def __init__(self, settings: Settings) -> None:
        self.base_url = str(settings.get("base_url", "")).rstrip("/")
        self.headless = bool(settings.get("headless", True))
        self._playwright: Any = None
        self._browser: Any = None
        self._pages: dict[str, Any] = {}

    def _start(self) -> Any:
        if self._browser is not None:
            return self._browser
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise Unreachable(
                "the browser system needs playwright: `uv sync --group browser && "
                "uv run playwright install chromium`"
            ) from exc
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=self.headless)
        except Exception as exc:
            raise Unreachable(f"the browser would not start: {exc}") from exc
        return self._browser

    def url(self, path: str) -> str:
        if not path:
            raise Unreachable("no url — write it as a `path` field")
        text = str(path)
        return text if text.startswith("http") else f"{self.base_url}{text if text.startswith('/') else '/' + text}"

    def opened(self, path: str) -> Any | None:
        """The page already open at this path, or nothing."""
        return self._pages.get(self.url(path))

    def open(self, path: str) -> Any:
        """Open a page at this path, and answer it."""
        url = self.url(path)
        page = self._start().new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=10_000)
        except Exception as exc:
            raise Unreachable(f"{url} did not answer: {exc}") from exc
        self._pages[url] = page
        return page

    def close(self, path: str) -> None:
        """Close the page open at this path, if one is."""
        page = self._pages.pop(self.url(path), None)
        if page is not None:
            page.close()

    def looking_at(self, path: str) -> Any:
        """The open page at this path, opening it if it is not open yet."""
        return self.opened(path) or self.open(path)

    def capture(self, where: Any) -> list[str]:
        """A screenshot of every open page, written under `where`, and the paths written.

        Called when a test goes red. A page that will not answer contributes nothing.
        """
        from pathlib import Path

        directory = Path(where)
        directory.mkdir(parents=True, exist_ok=True)
        written: list[str] = []
        for number, (url, page) in enumerate(sorted(self._pages.items())):
            shot = directory / f"page-{number}.png"
            try:
                page.screenshot(path=str(shot), full_page=True)
            except Exception:  # noqa: BLE001 - a page that will not answer leaves no picture
                continue
            written.append(str(shot))
            note = directory / f"page-{number}.txt"
            note.write_text(url, encoding="utf-8")
            written.append(str(note))
        return written

    def shut(self) -> None:
        for page in self._pages.values():
            page.close()
        self._pages.clear()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._browser = self._playwright = None


class Page(Resource):
    """A page open in the browser. Opening it is what makes it exist; closing it removes it."""

    #: A page is the address it is open at. There is no second way to recognise one.
    path: Resource.Key[str]

    browser = DriverProperty[Browser]("browser")

    @override
    def find(self) -> Payload | None:
        page = self.browser.opened(self.path)
        if page is None:
            return None
        return {"url": self.browser.url(self.path), "path": self.path, "title": page.title()}

    @override
    def create(self) -> Payload:
        page = self.browser.open(self.path)
        url = self.browser.url(self.path)
        return {"url": url, "path": self.path, "title": page.title()}

    @override
    def delete(self) -> None:
        self.browser.close(self.path)


register_system(Page, Browser, "page")


# --- The words this system brings ------------------------------------------------------------------
#
# Using an interface is not a concept in ATF's model. It is this system's vocabulary, and it is met
# by somebody doing browser work and by nobody else.
#
# Every one of these asks by **role and accessible name**. That is what a screen reader announces,
# and it is the thing worth claiming on — a CSS class is not.


def _page(atf: Any) -> Any:
    """The one page this scenario is looking at.

    A scenario arranges exactly one `page`, so there is nothing to disambiguate here — two of a kind
    in scope was already refused at collection.
    """
    looking = [node for node in atf.arranged if declaration_of(node).system == "browser.page"]
    if not looking:
        claims.fail("this sentence is about a page, and the scenario arranged none")
    return atf.ground.drivers["browser"].looking_at(looking[-1].path)


def _found(atf: Any, role: str, name: str) -> Any:
    """The control, or a failure naming what was there instead."""
    control = _page(atf).get_by_role(role, name=name)
    if control.count() == 0:
        claims.fail(f'no {role} "{name}" on the page\n    {_instead(atf, role)}')
    return control


def _instead(atf: Any, role: str) -> str:
    """What is on the page with that role, which is what a wrong name most wants to know."""
    named = [
        (one.get_attribute("aria-label") or (one.text_content() or "").strip())
        for one in _page(atf).get_by_role(role).all()
    ]
    if not named:
        return f"there is no {role} on the page at all"
    return f"{role}s on the page: " + ", ".join(f'"{one}"' for one in named if one)


@check('the {role} "{name}" is showing')
def _showing(role: str, name: str, atf: Any) -> tuple[bool, str]:
    """That control is on the page."""
    return _page(atf).get_by_role(role, name=name).count() > 0, _instead(atf, role)


@check('the {role} "{name}" is not showing')
def _not_showing(role: str, name: str, atf: Any) -> tuple[bool, str]:
    """That control is not on the page."""
    return _page(atf).get_by_role(role, name=name).count() == 0, "it is on the page"


@check('the {role} "{name}" reads "{text}"')
def _reads(role: str, name: str, text: str, atf: Any) -> tuple[bool, str]:
    """That control's own text is exactly this."""
    said = (_found(atf, role, name).first.text_content() or "").strip()
    return said == text, f"it reads {said!r}"


@check('the {role} "{name}" is disabled')
def _disabled(role: str, name: str, atf: Any) -> tuple[bool, str]:
    """That control cannot be used."""
    return not _found(atf, role, name).first.is_enabled(), "it is enabled"


@check('the {role} "{name}" is enabled')
def _enabled(role: str, name: str, atf: Any) -> tuple[bool, str]:
    """That control can be used."""
    return _found(atf, role, name).first.is_enabled(), "it is disabled"


@check('the words "{words}" are showing')
def _words_showing(words: str, atf: Any) -> tuple[bool, str]:
    """This text is somewhere on the page."""
    held = _page(atf).get_by_text(words, exact=False).count() > 0
    return held, f'"{words}" is not on the page'


@check('the words "{words}" are not showing')
def _words_not_showing(words: str, atf: Any) -> tuple[bool, str]:
    """This text is nowhere on the page."""
    held = _page(atf).get_by_text(words, exact=False).count() == 0
    return held, f'"{words}" is on the page'


@act('I click the {role} "{name}"')
def _click(role: str, name: str, atf: Any) -> None:
    """Click it."""
    _page(atf).get_by_role(role, name=name).first.click()


@act('I type "{text}" into the {role} "{name}"')
def _type_into(text: str, role: str, name: str, atf: Any) -> None:
    """Put this text into that field."""
    _page(atf).get_by_role(role, name=name).first.fill(text)


@act('I choose "{option}" from the {role} "{name}"')
def _choose(option: str, role: str, name: str, atf: Any) -> None:
    """Choose that option from that control."""
    _page(atf).get_by_role(role, name=name).first.select_option(label=option)
