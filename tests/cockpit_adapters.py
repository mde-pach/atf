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

import atexit
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
from atf.materializer import EPHEMERAL

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
        # Which copy of ATF the served cockpit runs. Inherited from `PYTHONPATH` rather than named
        # by a variable of this suite's own: the mutation guard runs the whole suite with it pointing
        # at a deliberately broken tree, and inheriting is what carries that through to the server.
        inherited = next(filter(None, os.environ.get("PYTHONPATH", "").split(os.pathsep)), "")
        self.source = Path(settings.get("atf_src") or inherited or REPO / "src")
        self._running: dict[str, subprocess.Popen[bytes]] = {}
        # Which workspace each kept server is serving, so a second scenario over the same suite is
        # handed the one already up rather than starting another.
        self._serving: dict[str, str] = {}
        # Belt and braces. `close` is called when the run ends and is enough for a run that ends;
        # a server holding a port is a bad thing to leave behind after one that does not — a crash,
        # a `Ctrl-C`, a worker killed. This costs nothing and covers all three.
        atexit.register(self.close)

    def find(self, node: Node, ctx: Context) -> Record | None:
        """The server already running over this workspace, where the node is one that is kept.

        A `private_cockpit` is ephemeral and is never reused: the scenario that presses Run writes
        run history into the suite it is serving, and the next scenario asking how many have never
        run must not be reading that. Every other cockpit is read through pages that only GET, so
        one server does for all of them — and starting one costs the better part of a second.
        """
        if node.lifecycle == EPHEMERAL:
            return None
        workspace = str(ctx.resolve(node.body["workspace"]))
        url = self._serving.get(workspace)
        return {"url": url, "workspace": workspace} if url and self._alive(url) else None

    def create(self, node: Node, body: Record, ctx: Context) -> Record:
        workspace = Path(str(body["workspace"]))
        if not (workspace / "atf.yaml").is_file():
            raise ValueError(f"{node.id}: no suite at {workspace}")

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
        if node.lifecycle != EPHEMERAL:
            self._serving[str(workspace)] = url
        return {"url": url, "workspace": str(workspace)}

    def delete(self, node: Node, record: Record, ctx: Context) -> None:
        self._stop(str(record.get("url")))

    def close(self) -> None:
        """Stop every server kept for the session. Called once, when the run ends.

        Without this a shared cockpit would outlive the run as an orphan holding a port, which is
        why `Materializer.close` had to start being called before any of this was possible.
        """
        for url in list(self._running):
            self._stop(url)
        self._serving.clear()

    def _stop(self, url: str) -> None:
        process = self._running.pop(url, None)
        self._serving = {where: served for where, served in self._serving.items() if served != url}
        if process is None:
            return
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=10)
        if process.poll() is None:
            process.kill()

    def _alive(self, url: str) -> bool:
        """Whether the server this adapter started is still running. Asked of the process, not of it.

        This used to `GET /` with a one-second timeout, and that was a real bug rather than an
        inefficiency. The overview is the *most* expensive page the cockpit serves — rendering it
        triggers a discovery pass — so a server that was perfectly alive but busy answered too
        slowly, the probe gave up, and a scenario started a second cockpit over the same suite and
        leaked the first. Under a fixed order the cockpit scenarios run together and it rarely
        happened; under `pytest-randomly` they interleave and it happened constantly. The suite took
        four times as long, and the orphaned servers I found earlier were these.

        A subprocess that has not exited is running. That is the whole question, it costs nothing,
        and it cannot time out.
        """
        process = self._running.get(url)
        return process is not None and process.poll() is None


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
