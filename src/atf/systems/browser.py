"""The `browser` driver, and `@page(...)` — a page opened in it and looked at by role."""

from __future__ import annotations

from typing import Any, TypedDict

from ..declare import Unreachable, adapter, driver
from ..spi import Record, Resource


@driver("browser")
class Browser:
    """One browser, and the pages opened in it.

    A step asks for this by the name `browser`; the `page` adapter works through it.
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
            from playwright.sync_api import sync_playwright  # noqa: PLC0415
        except ImportError as exc:
            raise Unreachable(
                "the browser system needs playwright: `uv sync --group browser && "
                "uv run playwright install chromium`"
            ) from exc
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=self.headless)
        except Exception as exc:  # noqa: BLE001 - a browser that will not launch is unreachable
            raise Unreachable(f"the browser would not start: {exc}") from exc
        return self._browser

    def url(self, resource: Resource) -> str:
        written = resource.values.get("path") or resource.values.get("url") or resource.options.get("url")
        if not written:
            raise Unreachable(f'{resource.kind}: no url — write it as a `path` field or @page(url="...")')
        text = str(written)
        return text if text.startswith("http") else f"{self.base_url}{text if text.startswith('/') else '/' + text}"

    def opened(self, resource: Resource) -> Any | None:
        """The page already open for this resource, or nothing."""
        return self._pages.get(self.url(resource))

    def open(self, resource: Resource) -> Any:
        """Open a page at this resource's url, and answer it."""
        url = self.url(resource)
        page = self._start().new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=10_000)
        except Exception as exc:  # noqa: BLE001
            raise Unreachable(f"{url} did not answer: {exc}") from exc
        self._pages[url] = page
        return page

    def close(self, resource: Resource) -> None:
        """Close the page open for this resource, if one is."""
        page = self._pages.pop(self.url(resource), None)
        if page is not None:
            page.close()

    def looking_at(self, resource: Resource) -> Any:
        """The open page for this resource, opening it if it is not open yet."""
        return self.opened(resource) or self.open(resource)

    def capture(self, where: Any) -> list[str]:
        """A screenshot of every open page, written under `where`, and the paths written.

        Called when a test goes red. A page that will not answer contributes nothing.
        """
        from pathlib import Path  # noqa: PLC0415

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


@adapter("page", driver="browser")
class Page:
    """A page open in the browser. Opening it is what makes it exist; closing it removes it."""

    class Options(TypedDict, total=False):
        """What the decorator takes, per resource."""

        url: str

    #: A page is the address it is open at. There is no second way to recognise one.
    recognised_by = ("path",)

    def __init__(self, browser: Browser) -> None:
        self.browser = browser

    def find(self, resource: Resource) -> Record | None:
        page = self.browser.opened(resource)
        if page is None:
            return None
        return {"url": self.browser.url(resource), "path": resource.values.get("path", ""), "title": page.title()}

    def create(self, resource: Resource) -> Record:
        page = self.browser.open(resource)
        url = self.browser.url(resource)
        return {"url": url, "path": resource.values.get("path", url), "title": page.title()}

    def delete(self, resource: Resource, found: Record) -> None:
        self.browser.close(resource)
