"""Collecting a `.feature` file directly, so a feature needs no Python beside it.

pytest-bdd binds a feature to pytest through a module that calls `scenarios("…")`. For a feature
that needs step code of its own that module is the natural home for it — but for one written
entirely in the vocabulary ATF already provides, it is a file whose whole content is an import and
a call, written once per feature and never read again. It is also an error path: the composer has
to notice a feature nobody bound, offer to write the module, and explain what it is for.

So ATF collects a `.feature` itself when nothing else has. The file becomes a module that was never
on disk, holding one test per scenario, built with pytest-bdd's own public `scenario()` decorator —
so what runs, what a failure looks like and what the report says are all exactly as before.

**What an auto-collected feature can reach.** pytest-bdd resolves a step to a *fixture*, and a step
defined in a module is visible only inside it. A feature collected here has no module, so it can
use: every step ATF defines, every [phrase](phrasebook.py), and anything declared in a `conftest.py`
above it. A feature that needs a `@when` of its own still wants a module — or the step moves to a
`conftest.py`, where every feature can see it. That is the same rule as before, said out loud.

**A feature some module already binds is left alone.** Collecting it here as well would run every
scenario in it twice, and the module is the one that can see its steps.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pytest_bdd import scenario as bind_scenario
from typing_extensions import override

# pytest-bdd's own parse, rather than ATF's: `scenario()` parses the file again itself and raises
# if a name does not match, so the two enumerations have to agree exactly.
from pytest_bdd.feature import get_feature as _get_feature  # isort: skip
from pytest_bdd.scenario import get_python_name_generator as _test_names  # isort: skip

SUFFIX = ".feature"


def binds(specs_dir: Path, feature: Path) -> bool:
    """Whether some module already hands this feature to pytest.

    A text scan, because at collection time the modules that would bind it have not been imported
    yet — and the answer has to be known *before* deciding to collect the feature a second way.
    """
    for path in Path(specs_dir).rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "scenarios(" in text and feature.name in text:
            return True
    return False


def module_for(path: Path) -> ModuleType:
    """A module that was never on disk, holding one test per scenario in this feature."""
    feature = _get_feature(str(path.parent), path.name)
    module = ModuleType(f"atf_feature_{path.stem}")
    module.__file__ = str(path)
    module.__doc__ = f"{path.name}, collected by ATF: no module binds it, and it needs none."

    for name in feature.scenarios:
        # The same decorator a hand-written binding module would use, with the feature located
        # explicitly — `scenario()` otherwise resolves it against the *calling* module's directory,
        # which here is ATF's own source tree.
        made = bind_scenario(path.name, name, features_base_dir=str(path.parent))(_nothing)
        for test_name in _test_names(name):
            if not hasattr(module, test_name):
                setattr(module, test_name, made)
                break
    return module


def _nothing() -> None:
    """The body of a generated test. Every step is in the feature file; there is nothing to add."""


class FeatureModule(pytest.Module):
    """A `.feature` collected as though it were the module nobody wrote."""

    @override
    def _getobj(self) -> ModuleType:
        return module_for(Path(self.path))


def collect(file_path: Path, parent: Any, specs_dir: Path) -> Any:
    """The collector for one path, or `None` when ATF has nothing to say about it."""
    if file_path.suffix != SUFFIX:
        return None
    if not _inside(file_path, specs_dir):
        return None
    if binds(specs_dir, file_path):
        return None
    return FeatureModule.from_parent(parent, path=file_path)


def _inside(path: Path, specs_dir: Path) -> bool:
    """Only what the manifest calls the specs directory. A `.feature` elsewhere is not ATF's."""
    try:
        path.resolve().relative_to(Path(specs_dir).resolve())
    except ValueError:
        return False
    return True
