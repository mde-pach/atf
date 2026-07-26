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
