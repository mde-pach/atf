"""Starts the stub environment before ATF bootstraps, then hands over to the plugin."""

import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

if not os.environ.get("SELFTEST_BACKEND"):
    from stub_backend import StubBackend

    os.environ.setdefault("SELFTEST_ACTOR", "selftest")
    _backend = StubBackend(actor=os.environ["SELFTEST_ACTOR"])
    os.environ["SELFTEST_BACKEND"] = _backend.start()

pytest_plugins = ["atf.plugin"]


def pytest_collection_modifyitems(items):
    """Skip the browser-driven scenarios when there is no browser, rather than failing them.

    ATF reads `@browser` as a tag and shows it; acting on a tag is the suite's job, and this is the
    hook the documentation describes for exactly that. Everything not tagged still runs, so a
    checkout without `--group browser` is still a green, meaningful self-test.
    """
    import pytest
    from cockpit_adapter import browser_available

    if browser_available():
        return
    skip = pytest.mark.skip(reason="no browser here — `uv sync --group browser && uv run playwright install chromium`")
    for item in items:
        if "browser" in {mark.name for mark in item.iter_markers()}:
            item.add_marker(skip)
