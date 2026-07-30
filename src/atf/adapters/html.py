"""A page as the server sent it, and what is on it — by role and accessible name, no browser.

```yaml
catalog:
  system: html
  mode: data
  body:
    at: /catalog
```

```gherkin
Given the page "catalog"
Then the heading "Catalog" is showing
And the link "Compose" is showing
```

Most of what a suite claims about a server-rendered interface is true of the *response*: the
headings are in it, the links are in it, the rows of the table are in it. Asking those questions of
a real browser costs a browser on every machine that runs the suite, and it is the reason a UI
suite is the first thing a team stops running.

So this adapter answers them from the HTML, through the same [reading](../accessible.py) a screen
reader would do — and a scenario written against it says exactly what it would say against the
`browser` system. Which one answers is a property of the environment, not of the sentence.

**What it cannot do, it does not pretend to do.** It cannot click, because a response is not a
running page. It cannot see a stylesheet apply, a fragment swap in, or a combobox open. Those are
what `browser` is for, and a suite is entitled to both: the cheap claims on every machine, the
expensive ones where a browser exists.

**A page is `mode: data`** — somewhere to look, never something ATF makes — and what `find` brings
back is deliberately thin: where it is, what came back, what it is called. Everything else worth
claiming is a control, and a control is named in the scenario rather than in the catalog.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from ..model.catalog import Node
from . import Context, NoopDelete, Record
from .control import Control, Page

# Where a page node says to look. A path is joined to the adapter's `base_url`; anything absolute is
# taken as it stands, which is what lets one suite reach two hosts.
AT = "at"

DEFAULT_TIMEOUT = 10.0


@dataclass
class HtmlAdapter(NoopDelete):
    """The `html` system: pages to read, and the last one read, for the steps that claim about one."""

    base_url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = DEFAULT_TIMEOUT
    follow_redirects: bool = True
    _page: Page | None = field(default=None, init=False, repr=False)
    _where: str = field(default="", init=False, repr=False)

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> HtmlAdapter:
        return cls(
            base_url=str(settings.get("base_url", "")),
            headers={str(key): str(value) for key, value in (settings.get("headers") or {}).items()},
            timeout=float(settings.get("timeout", DEFAULT_TIMEOUT)),
            follow_redirects=bool(settings.get("follow_redirects", True)),
        )

    # ---- SPI ----------------------------------------------------------------

    def find(self, node: Node, ctx: Context) -> Record | None:
        """Fetch this page and describe what came back.

        A response that never arrived is nothing — which is what makes `the page "…" is gone` mean
        what it says. A response that arrived saying no is still a page: a 404 has a heading on it,
        and a suite is entitled to claim what it says.
        """
        where = node.body.get(AT)
        if where is None:
            raise ValueError(f"{node.id}: a page needs `{AT}` — where to look")

        url = self.url_for(str(ctx.resolve(where)))
        try:
            response = httpx.get(
                url, headers=self.headers, timeout=self.timeout, follow_redirects=self.follow_redirects
            )
        except httpx.HTTPError:
            return None

        self._page = Page(response.text)
        self._where = url
        return {
            AT: where,
            "url": url,
            "status": response.status_code,
            "title": self._page.title,
        }

    def create(self, node: Node, body: Record, ctx: Context) -> Record:
        raise ValueError(
            f"{node.id}: a page is somewhere to look, not something ATF makes. "
            "Declare its type `mode: data`."
        )

    def url_for(self, where: str) -> str:
        if "://" in where:
            return where
        return f"{self.base_url.rstrip('/')}/{where.lstrip('/')}"

    # ---- what is on the page a scenario opened ------------------------------

    def controls(self, role: str = "", name: str = "", *, wait: float = 0.0) -> list[Control]:
        """Everything showing with this role and this name. `wait` is ignored: nothing will change.

        A response is finished when it arrives. Waiting for a fragment to swap in is a claim about
        a page that is *running*, which is the `browser` system's half of this.
        """
        return self._showing().controls(role, name)

    def says(self, text: str, *, wait: float = 0.0) -> bool:
        return self._showing().says(text)

    def looking_at(self) -> str:
        return self._where

    def _showing(self) -> Page:
        if self._page is None:
            raise ValueError(
                "no page has been read — a step above this one has to say which page it is about, "
                'with `Given the <page type> "<name>"`'
            )
        return self._page
