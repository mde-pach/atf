"""`@browser(...)` — a page, opened and looked at.

Its settings are `base_url` and `headless`; its option is `url`. A page is not created, it is
opened, so a browser resource is normally declared `when_absent="observe"`: an absent one is a fact
about the environment rather than an error, and whether that fails is decided by what the test
claims about it.

```python
@browser(when_absent="observe", unique_by="path")
class Screen:
    path: str
```

**Everything is asked for by role and accessible name, never by selector.** `get_by_role` is
Playwright's own accessibility query, so a claim about a heading is a claim about what a screen
reader would announce — which is the thing worth testing and the thing a CSS class is not.

Playwright is not a dependency of ATF. Without it this system is `unreachable`, which is the honest
answer: the question could not be asked, and no test silently passes on nothing.
"""

from __future__ import annotations

from typing import Any, TypedDict

from ..declare import Unreachable, adapter, declaration_of, values_of
from ..spi import Record


@adapter("browser")
class Browser:
    """One browser, and the pages opened in it."""

    class Options(TypedDict, total=False):
        """What the decorator takes, per resource."""

        url: str

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

    def _url(self, resource: Any) -> str:
        declaration = declaration_of(resource)
        written = values_of(resource).get("path") or values_of(resource).get("url") or declaration.options.get("url")
        if not written:
            raise Unreachable(f'{declaration.kind}: no url — write it as @browser(url="...") or as a field')
        text = str(written)
        return text if text.startswith("http") else f"{self.base_url}{text if text.startswith('/') else '/' + text}"

    def page(self, resource: Any) -> Any:
        """The open page for this resource, opening it if it is not open yet."""
        url = self._url(resource)
        if url not in self._pages:
            page = self._start().new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=10_000)
            except Exception as exc:  # noqa: BLE001
                raise Unreachable(f"{url} did not answer: {exc}") from exc
            self._pages[url] = page
        return self._pages[url]

    def find(self, resource: Any) -> Record | None:
        url = self._url(resource)
        try:
            page = self.page(resource)
        except Unreachable:
            raise
        return {"url": url, "path": values_of(resource).get("path", url), "title": page.title()}

    def create(self, resource: Any) -> Record:
        """A page is not created. Declaring one `when_absent="observe"` is how that is said."""
        raise Unreachable(
            f"{declaration_of(resource).kind}: a page is opened, never created — "
            f'declare it `when_absent="observe"`'
        )

    def update(self, resource: Any, found: Record, changes: Record) -> Record:
        raise Unreachable(f"{declaration_of(resource).kind}: a page is looked at, not written to")

    def delete(self, resource: Any, found: Record) -> None:
        page = self._pages.pop(self._url(resource), None)
        if page is not None:
            page.close()

    def close(self) -> None:
        for page in self._pages.values():
            page.close()
        self._pages.clear()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._browser = self._playwright = None
