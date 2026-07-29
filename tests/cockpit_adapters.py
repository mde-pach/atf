"""The one adapter left that this suite has to write: a running cockpit.

    cockpit   ephemeral   a running `atf serve` over a workspace — created, then torn down

Everything else about the interface is ATF's own now. A `page` is the `html` system — what a URL
sent, asked what is on it by role and accessible name — and a `screen` is the `browser` system, the
same questions asked of a page that has actually run. This module used to hold both, plus a
selector engine, plus eleven catalog nodes each carrying one CSS selector.

The dependency chain is the ordinary one: a page declares the cockpit that serves it, and the
cockpit declares the workspace it serves — so provisioning a page scaffolds a suite, starts a
server, fetches the page and tears it all down afterwards.

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

from atf.adapters import Context, Record, register
from atf.catalog import Node

HERE = Path(__file__).parent
REPO = HERE.parent

STARTUP_TIMEOUT = 30.0


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
        self.source = Path(settings.get("atf_src") or os.environ.get("ATF_TESTS_SRC") or REPO / "src")
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


register("cockpit", CockpitAdapter)
