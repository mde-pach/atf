"""Finding `atf/` beside the manifest, importing it, and reading what it declared."""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import graph
from .declare import (
    ADAPTERS,
    Declaration,
    DeclarationError,
    declaration_of,
    instance_of,
    is_declared,
    is_resource,
)
from .manifest import SUITE_DIR, Manifest, load


class SuiteError(Exception):
    """Raised when what was found cannot be loaded, or does not read as a suite."""


#: A module in a suite that is not part of its vocabulary: a Python test, a private helper, pytest's
#: own file. Everything else is imported so that whatever it declares is registered.
def _is_library(path: Path) -> bool:
    return path.name.startswith("test_")


def _is_skipped(path: Path) -> bool:
    return path.name.startswith(("test_", "_")) or path.name == "conftest.py"


@dataclass(frozen=True)
class Suite:
    """Everything a suite declared, and nothing about any environment it might run against."""

    manifest: Manifest
    kinds: dict[str, type] = field(default_factory=dict)
    instances: dict[str, Any] = field(default_factory=dict)
    adapters: dict[str, type] = field(default_factory=dict)
    #: Every `test_*.py` in the suite — the library surface. Counted by `atf plan`, never a spec.
    library: tuple[Path, ...] = ()

    def declaration(self, kind: str) -> Declaration:
        try:
            return declaration_of(self.kinds[kind])
        except KeyError:
            known = ", ".join(sorted(self.kinds)) or "none"
            raise SuiteError(f"no kind called {kind!r} (declared: {known})") from None

    def resource(self, name: str) -> Any:
        try:
            return self.instances[name]
        except KeyError:
            known = ", ".join(sorted(self.instances)) or "none"
            raise SuiteError(f"nothing called {name!r} (declared: {known})") from None

    @property
    def order(self) -> list[Any]:
        """Every declared resource, in the order they would be made."""
        return graph.order(self.instances.values())


def fixture_name(kind: str) -> str:
    """`Owner` -> `owner`, `TodoList` -> `todo_list` — the name a scenario says and a test asks for."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", kind).lower()


def modules_in(suite: Path) -> list[Path]:
    """Every module of a suite's vocabulary, in a stable order."""
    if not suite.is_dir():
        return []
    return [path for path in sorted(suite.rglob("*.py")) if not _is_skipped(path)]


def library_in(suite: Path) -> list[Path]:
    """Every Python test in a suite. Not the spec, and counted so that saying so is unavoidable."""
    if not suite.is_dir():
        return []
    return [path for path in sorted(suite.rglob("*.py")) if _is_library(path)]


def load_suite(manifest: Manifest | None = None) -> Suite:
    """Find the suite beside the manifest, import it, then read what was declared."""
    manifest = manifest or load()
    where = manifest.suite
    if not where.is_dir():
        raise SuiteError(
            f"{manifest.path.parent} has no {SUITE_DIR}/ beside its {manifest.path.name}.\n"
            f"  A suite is one directory: the things, the words and the scenarios. "
            f"Run `atf init` to start one."
        )

    modules = [_import_file(path, where) for path in modules_in(where)]

    kinds: dict[str, type] = {}
    instances: dict[str, Any] = {}
    problems: list[str] = []

    for module in modules:
        for attribute, value in vars(module).items():
            if attribute.startswith("_"):
                continue
            if is_declared(value):
                _collect_kind(value, kinds, problems)
            elif is_resource(value):
                _collect_instance(attribute, value, instances, problems)

    _refuse_name_collisions(kinds, instances, problems)
    if problems:
        raise SuiteError("this suite cannot be read:\n  - " + "\n  - ".join(problems))

    return Suite(
        manifest=manifest,
        kinds=kinds,
        instances=instances,
        adapters=dict(ADAPTERS),
        library=tuple(library_in(where)),
    )


def _collect_kind(value: type, kinds: dict[str, type], problems: list[str]) -> None:
    kind = declaration_of(value).kind
    seen = kinds.get(kind)
    if seen is None:
        kinds[kind] = value
    elif seen is not value:
        problems.append(
            f"two kinds are called {kind!r}: "
            f"{seen.__module__}.{seen.__name__} and {value.__module__}.{value.__name__}"
        )


def _collect_instance(attribute: str, value: Any, instances: dict[str, Any], problems: list[str]) -> None:
    record = instance_of(value)
    if record.name and record.name != attribute:
        problems.append(
            f"the resource {record.name!r} is also bound to {attribute!r}; a thing has one name, "
            f"which is its variable's"
        )
        return
    seen = instances.get(attribute)
    if seen is not None and seen is not value:
        problems.append(f"two things are called {attribute!r}, declared in different modules")
        return
    record.name = attribute
    instances[attribute] = value


def _refuse_name_collisions(kinds: dict[str, type], instances: dict[str, Any], problems: list[str]) -> None:
    """A resource named after a kind shadows the name that means "any of that kind"."""
    by_fixture: dict[str, list[str]] = {}
    for kind in kinds:
        by_fixture.setdefault(fixture_name(kind), []).append(f"the kind {kind}")
    for name in instances:
        by_fixture.setdefault(name, []).append(f"the resource {name}")
    for name, claimants in sorted(by_fixture.items()):
        if len(claimants) > 1:
            problems.append(f"{' and '.join(claimants)} both want the name {name!r} — rename one")


def _import_file(path: Path, where: Path) -> Any:
    """Import one module of the suite, under the plain name a module beside it would import it by.

    The suite directory goes on the front of `sys.path` and the project behind it, so `words.py` is
    `words` and the product beside the manifest is importable by its own name.
    """
    where = where.resolve()
    # Always to the front, never merely present: a second suite loaded in the same process must
    # win over the first, and then the first must win again if it is reloaded.
    if str(where) in sys.path:
        sys.path.remove(str(where))
    sys.path.insert(0, str(where))
    # The project, appended so a suite can import the product it tests. Never prepended: a
    # directory called `atf` beside the manifest would shadow the installed package.
    beside = str(where.parent)
    if beside not in sys.path:
        sys.path.append(beside)

    name = _module_name(path, where)
    _evict_if_stale(name, path)
    try:
        if name in sys.modules:
            return sys.modules[name]
        return importlib.import_module(name)
    except DeclarationError as exc:
        raise SuiteError(f"{path}: {exc}") from exc
    except Exception as exc:
        raise SuiteError(f"{path}: {type(exc).__name__}: {exc}") from exc


def _evict_if_stale(name: str, path: Path) -> None:
    """Drop a cached module of this name that came from somewhere else.

    `sys.modules` is keyed by name, and a name is only unique inside one suite. Two suites both
    holding a `things.py` therefore collide, and the second silently gets the first's declarations.
    Anything loading more than one suite in a process meets this: the editor, a tool comparing two
    suites, and ATF's own tests.
    """
    cached = sys.modules.get(name)
    if cached is None or getattr(cached, "__file__", None) == str(path):
        return
    for cached_name in [n for n in sys.modules if n == name or n.startswith(f"{name}.")]:
        del sys.modules[cached_name]


def _module_name(path: Path, where: Path) -> str:
    """The name this file has when the suite directory is on the path."""
    try:
        relative = path.resolve().relative_to(where)
    except ValueError:
        raise SuiteError(f"{path}: sits outside {where}, and a suite is one directory") from None
    parts = relative.with_suffix("").parts
    bad = [part for part in parts if not re.fullmatch(r"[A-Za-z_]\w*", part)]
    if bad:
        raise SuiteError(f"{path}: {', '.join(bad)} is not importable as a Python module name")
    return ".".join(parts)
