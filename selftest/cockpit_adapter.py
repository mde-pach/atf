"""Adapters that make ATF's own interface into resources, so ATF can test its front end.

Three types, three adapters, and the ordinary catalog machinery holds them together:

    cockpit   ephemeral   a running `atf serve` over a workspace — created, then torn down
    page      reference   one URL on that cockpit; ATF looks at it and never creates it
    element   reference   what one selector matches in what that URL *sent*

A `screen` — what is there after the stylesheet applied and htmx swapped — is ATF's own `browser`
adapter now, and it carries no selectors at all. These three are about the HTML a server sent,
which is a different question and a far cheaper one to ask.

A page and an element are `mode: reference` because that is what they are: things ATF can observe
and could never make. That is also what makes them safe — nothing here can change the cockpit it
is reading. The dependency chain is the same one any catalog uses: an element declares the page it
is on, the page declares the cockpit it is served by, and the cockpit declares the workspace it
serves, so provisioning an element starts a server and tears it down afterwards.

The point of doing it this way rather than with a test helper: every scenario written against these
resources is written the way a consumer writes one, through the same steps, and can be composed in
the cockpit's own interface. If that is awkward, the framework is awkward.
"""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from atf.adapters import Context, NoopDelete, Record, register
from atf.catalog import Node

HERE = Path(__file__).parent
REPO = HERE.parent

# ATF loads an adapter module from its path rather than by import, deliberately: a suite named
# `types.py` must not shadow the stdlib for the rest of the process. That leaves this module's own
# neighbours unimportable, so it puts its directory on the path itself — a choice the suite is
# entitled to make about its own file names, and one the framework should not make for it.
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import html_select  # noqa: E402  — only importable once the line above has run

STARTUP_TIMEOUT = 30.0
READ_TIMEOUT = 10.0

# Fields the adapters put on an element record themselves. An attribute of the same name on the
# HTML element loses, because a scenario asserting on `count` means how many matched.
RESERVED = ("selector", "page", "count", "text")


# ---- a running cockpit ------------------------------------------------------


class CockpitAdapter:
    """`atf serve` over a provisioned workspace, for the length of one scenario.

    Ephemeral by necessity as much as by choice: two scenarios sharing a server would share
    whatever the first one provisioned into it.
    """

    def __init__(self, settings: dict[str, Any]) -> None:
        # Which copy of ATF the served cockpit runs, same override the CLI-under-test honours. The
        # mutation tests point it at a deliberately broken copy; if this ignored them, the scenarios
        # below would be testing the working tree while claiming to test that copy.
        self.source = Path(settings.get("atf_src") or os.environ.get("ATF_SELFTEST_SRC") or REPO / "src")
        self._running: dict[str, subprocess.Popen[bytes]] = {}

    def find(self, node: Node, ctx: Context) -> Record | None:
        return None  # ephemeral: never reused between scenarios

    def create(self, node: Node, body: Record, ctx: Context) -> Record:
        workspace = Path(str(body["workspace"]))
        if not (workspace / "atf.yaml").is_file():
            raise ValueError(f"{node['id']}: no suite at {workspace}")

        port = _free_port()
        url = f"http://127.0.0.1:{port}"
        process = subprocess.Popen(
            [sys.executable, "-m", "atf.cli", "serve", "--port", str(port)],
            cwd=workspace,
            env={
                **os.environ,
                "PYTHONPATH": os.pathsep.join([str(self.source), str(workspace)]),
                "ATF_MANIFEST": str(workspace / "atf.yaml"),
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._running[url] = process
        _wait_until_answering(url, process)
        return {"url": url, "workspace": str(workspace)}

    def delete(self, node: Node, record: Record, ctx: Context) -> None:
        process = self._running.pop(str(record.get("url")), None)
        if process is None:
            return
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=10)
        if process.poll() is None:
            process.kill()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_until_answering(url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        if process.poll() is not None:
            raise ValueError(f"the cockpit exited with {process.returncode} before it answered")
        try:
            httpx.get(url, timeout=1.0)
            return
        except httpx.HTTPError:
            time.sleep(0.05)
    process.kill()
    raise ValueError(f"the cockpit at {url} did not answer within {STARTUP_TIMEOUT:.0f}s")


# ---- a page, and what is on it ----------------------------------------------


class PageAdapter(NoopDelete):
    """One URL on a running cockpit. `find` fetches it; there is nothing to create."""

    def find(self, node: Node, ctx: Context) -> Record | None:
        cockpit = str(ctx.resolve(node["body"]["cockpit"]))
        path = str(node["body"]["path"])
        response = _fetch(cockpit, path)
        if response is None or response.status_code >= 400:
            return None
        document = html_select.parse(response.text)
        title = next((element.text for element in html_select.select(document, "title")), "")
        return {
            "cockpit": cockpit,
            "path": path,
            "status": response.status_code,
            "title": title,
            "length": len(response.text),
        }

    def create(self, node: Node, body: Record, ctx: Context) -> Record:
        raise ValueError(f"{node['id']}: a page is observed, never created")


class ElementAdapter(NoopDelete):
    """What one selector matches on one page.

    `find` returns nothing when the selector matches nothing, which is what makes
    `Then the element "…" is gone` mean what it says.
    """

    def find(self, node: Node, ctx: Context) -> Record | None:
        page = str(ctx.resolve(node["body"]["page"]))
        selector = str(node["body"]["selector"])
        cockpit = str(ctx.resolve(node["body"]["cockpit"]))

        response = _fetch(cockpit, page)
        if response is None or response.status_code >= 400:
            return None

        matched = html_select.select(html_select.parse(response.text), selector)
        if not matched:
            return None

        first = matched[0]
        record: Record = {name: value for name, value in first.attrs.items() if name not in RESERVED}
        record.update(
            {
                "selector": selector,
                "page": page,
                "count": len(matched),
                "text": first.text,
            }
        )
        return record

    def create(self, node: Node, body: Record, ctx: Context) -> Record:
        raise ValueError(f"{node['id']}: an element is observed, never created")

    def browse(self, node: Node, ctx: Context, limit: int = 200) -> list[Record]:
        """Every element on the page carrying an id or a class — what a catalog can be written from.

        Answers "what is on this page at all?", which is how the cockpit's own Add-to-catalog flow
        turns a real page into declared resources.
        """
        cockpit = str(ctx.resolve(node["body"].get("cockpit", "")))
        page = str(ctx.resolve(node["body"].get("page", "")))
        response = _fetch(cockpit, page)
        if response is None or response.status_code >= 400:
            return []

        found: list[Record] = []
        for element in html_select.parse(response.text).walk():
            selector = _selector_for(element)
            if selector is None:
                continue
            found.append({"selector": selector, "page": page, "count": 1, "text": element.text[:120]})
            if len(found) >= limit:
                break
        return found


def _selector_for(element: html_select.Element) -> str | None:
    if element.attrs.get("id"):
        return f"#{element.attrs['id']}"
    classes = sorted(element.classes)
    return f"{element.tag}.{classes[0]}" if classes else None


def _fetch(cockpit: str, path: str) -> httpx.Response | None:
    try:
        return httpx.get(f"{cockpit.rstrip('/')}{path}", timeout=READ_TIMEOUT, follow_redirects=True)
    except httpx.HTTPError:
        return None


# ---- what the page becomes once it has run ----------------------------------


class BrowserUnavailable(Exception):
    """Playwright or its browser is not installed here."""


register("cockpit", CockpitAdapter)
register("page", lambda settings: PageAdapter())
register("element", lambda settings: ElementAdapter())
