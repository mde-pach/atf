"""A page in a real browser, and the controls on it named the way a person names them."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any

from ..model.catalog import Node
from . import Context, NoopDelete, Record
from .control import Control

# Where a page node says to go. A path is joined to the adapter's `base_url`; anything absolute is
# taken as it stands, which is what lets one suite reach two hosts.
AT = "at"


@dataclass
class BrowserAdapter(NoopDelete):
    """The `browser` system: pages to look at, and a live page for the steps that act on one."""

    base_url: str = ""
    headless: bool = True
    timeout: float = 10_000.0
    _play: Any = field(default=None, init=False, repr=False)
    _browser: Any = field(default=None, init=False, repr=False)
    _page: Any = field(default=None, init=False, repr=False)

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> BrowserAdapter:
        return cls(
            base_url=str(settings.get("base_url", "")),
            headless=bool(settings.get("headless", True)),
            timeout=float(settings.get("timeout", 10_000.0)),
        )

    # ---- availability -------------------------------------------------------

    def unavailable(self) -> str:
        """Why the scenarios that need a browser cannot run here — `""` when they can."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return "playwright is not installed — `uv sync --group browser`"
        try:
            with sync_playwright() as play:
                play.chromium.launch(headless=self.headless).close()
        except Exception as exc:  # noqa: BLE001 - "can we?" is never answered with an exception
            return f"no browser to drive — `uv run playwright install chromium` ({_short(exc)})"
        return ""

    # ---- SPI ----------------------------------------------------------------

    def find(self, node: Node, ctx: Context) -> Record | None:
        """Go to this page and describe what arrived.

        A page is `mode: data`: something to look at, never something ATF makes. What comes back is
        thin — where it is and what it is called. Everything else worth claiming is a control, and a
        control is named in the scenario, not in the catalog.
        """
        where = node.body.get(AT)
        if where is None:
            raise ValueError(f"{node.id}: a page needs `{AT}` — where to go")
        page = self.open(str(ctx.resolve(where)))
        return {AT: where, "url": page.url, "title": page.title()}

    def create(self, node: Node, body: Record, ctx: Context) -> Record:
        raise ValueError(
            f"{node.id}: a page is somewhere to look, not something ATF makes. "
            "Declare its type `mode: data`."
        )

    def close(self) -> None:
        for held in ("_page", "_browser", "_play"):
            thing = getattr(self, held)
            setattr(self, held, None)
            if thing is None:
                continue
            # Closing must never fail a run: what is being torn down is already finished with.
            with contextlib.suppress(Exception):
                (thing.stop if held == "_play" else thing.close)()

    # ---- the live page ------------------------------------------------------

    def open(self, where: str) -> Any:
        """Go somewhere, starting a browser first if this is the first page of the run."""
        page = self.page()
        page.goto(self.url_for(where), wait_until="load")
        return page

    def url_for(self, where: str) -> str:
        if "://" in where:
            return where
        return f"{self.base_url.rstrip('/')}/{where.lstrip('/')}"

    def page(self) -> Any:
        """The one page this run drives. Started on first use, so a suite that never looks pays nothing."""
        if self._page is not None:
            return self._page
        from playwright.sync_api import sync_playwright

        self._play = sync_playwright().start()
        self._browser = self._play.chromium.launch(headless=self.headless)
        self._page = self._browser.new_page()
        self._page.set_default_timeout(self.timeout)
        return self._page

    def showing(self) -> Any:
        """The page a step is about, or a refusal saying no scenario has opened one."""
        if self._page is None:
            raise ValueError(
                "no page is open — a step above this one has to say which page it is about, "
                'with `Given the <page type> "<name>"`'
            )
        return self._page

    # ---- what is on it ------------------------------------------------------
    #
    # The same three questions ATF's `html` system answers about a response, asked of a page that
    # has actually run. That is what lets one sentence mean one thing in both places: which system
    # a suite configures decides what a claim costs, never what it says.

    def controls(self, role: str = "", name: str = "", *, wait: float = 0.0) -> list[Control]:
        """Everything visible with this role, and this accessible name where one is given."""
        page = self.showing()
        found = page.get_by_role(role, name=name) if name else page.get_by_role(role)
        # Not arriving is an outcome this returns, never an error: the step above decides what an
        # empty list means, and for a negative claim an empty list is the answer it wants.
        with contextlib.suppress(Exception):
            found.first.wait_for(state="visible", timeout=wait or self.timeout)
        controls = []
        for index in range(found.count()):
            one = found.nth(index)
            if not one.is_visible():
                continue
            text = " ".join((one.text_content() or "").split())
            controls.append(
                Control(role=role, name=name or text, text=text, disabled=one.is_disabled())
            )
        return controls

    def says(self, text: str, *, wait: float = 0.0) -> bool:
        """Whether these words are readable somewhere on the page."""
        found = self.showing().get_by_text(text)
        try:
            found.first.wait_for(state="visible", timeout=wait or self.timeout)
        except Exception:  # noqa: BLE001 - not appearing is the answer, not a failure
            return False
        return True

    def looking_at(self) -> str:
        return self._page.url if self._page is not None else ""


def _short(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text.splitlines()[0][:120]

