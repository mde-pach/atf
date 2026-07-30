"""Reaching for the adapter a step needs, and saying so when this environment has none."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from ..adapters import Adapter
from ..engine.materializer import Materializer


def sole(engine: Materializer, capable: Callable[[Adapter], bool], none: str, several: str) -> Adapter:
    """The one adapter of a kind this environment configures.

    Fails the scenario with `none` where there is no such adapter and with `several` where there is
    more than one — each of which is a sentence naming what to write instead.
    """
    __tracebackhide__ = True
    able = [one for one in engine.adapters.values() if capable(one)]
    if not able:
        pytest.fail(none)
    if len(able) > 1:
        pytest.fail(several)
    return able[0]
