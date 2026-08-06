"""Importing what a manifest names, and reading the declarations that came back."""

from __future__ import annotations
import __future__  # noqa: I001 - the module, to recognise the import above in somebody else's file

import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import graph
from .declare import ADAPTERS, Declaration, DeclarationError, declaration_of, instance_of, is_declared, is_resource
from .manifest import Manifest, load


class SuiteError(Exception):
    """Raised when what the manifest names cannot be loaded, or does not read as a suite."""


@dataclass(frozen=True)
class Suite:
    """Everything a suite declared, and nothing about any environment it might run against."""

    manifest: Manifest
    kinds: dict[str, type] = field(default_factory=dict)
    instances: dict[str, Any] = field(default_factory=dict)
    adapters: dict[str, type] = field(default_factory=dict)

    def declaration(self, kind: str) -> Declaration:
        try:
            return declaration_of(self.kinds[kind])
        except KeyError:
            known = ", ".join(sorted(self.kinds)) or "none"
            raise SuiteError(f"no resource kind called {kind!r} (declared: {known})") from None

    def resource(self, name: str) -> Any:
        try:
            return self.instances[name]
        except KeyError:
            known = ", ".join(sorted(self.instances)) or "none"
            raise SuiteError(f"no resource called {name!r} (declared: {known})") from None

    @property
    def order(self) -> list[Any]:
        """Every declared resource, in the order they would be made."""
        return graph.order(self.instances.values())

    @property
    def unmet(self) -> list[graph.Unmet]:
        """Every requirement nothing named, across the whole suite."""
        return [problem for node in self.instances.values() for problem in graph.unmet(node)]


def fixture_name(kind: str) -> str:
    """`Owner` -> `owner`, `TodoList` -> `todo_list` — the name a scenario says and a test asks for."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", kind).lower()


def load_suite(manifest: Manifest | None = None) -> Suite:
    """Import what the manifest names, then read what was declared."""
    manifest = manifest or load()

    for path in manifest.extensions:
        _import_file(path, manifest.root)

    modules = [_import_file(path, manifest.root) for path in manifest.resources]

    kinds: dict[str, type] = {}
    instances: dict[str, Any] = {}
    problems: list[str] = []

    for module in modules:
        _refuse_future_annotations(module, problems)
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
    )


def _collect_kind(value: type, kinds: dict[str, type], problems: list[str]) -> None:
    kind = declaration_of(value).kind
    seen = kinds.get(kind)
    if seen is None:
        kinds[kind] = value
    elif seen is not value:
        problems.append(
            f"two resource kinds are called {kind!r}: "
            f"{seen.__module__}.{seen.__name__} and {value.__module__}.{value.__name__}"
        )


def _collect_instance(attribute: str, value: Any, instances: dict[str, Any], problems: list[str]) -> None:
    record = instance_of(value)
    if record.name and record.name != attribute:
        problems.append(
            f"the resource {record.name!r} is also bound to {attribute!r}; a resource has one name, "
            f"which is its variable's"
        )
        return
    seen = instances.get(attribute)
    if seen is not None and seen is not value:
        problems.append(f"two resources are called {attribute!r}, declared in different modules")
        return
    record.name = attribute
    instances[attribute] = value


def _refuse_name_collisions(kinds: dict[str, type], instances: dict[str, Any], problems: list[str]) -> None:
    """A resource named after a kind shadows the fixture that means "any of that kind"."""
    by_fixture: dict[str, list[str]] = {}
    for kind in kinds:
        by_fixture.setdefault(fixture_name(kind), []).append(f"the kind {kind}")
    for name in instances:
        by_fixture.setdefault(name, []).append(f"the resource {name}")
    for name, claimants in sorted(by_fixture.items()):
        if len(claimants) > 1:
            problems.append(f"{' and '.join(claimants)} both want the name {name!r} — rename one")


def _refuse_future_annotations(module: Any, problems: list[str]) -> None:
    """A resources module states its shape in annotations, so they must be types, not strings.

    Under that import `email: str` is the four characters, not the class.
    """
    if getattr(module, "annotations", None) is __future__.annotations:
        problems.append(
            f"{module.__file__}: remove `from __future__ import annotations`. A resources module "
            f"declares its shape in annotations, and under that import they are strings"
        )


def _import_file(path: Path, root: Path) -> Any:
    """Import one file the manifest names, under the name the suite's own code would import it by.

    Risk 7 of MIGRATION.md is that a resource's name comes from a variable, so the same file
    imported under two names declares two of everything. That is why this puts the suite root on
    `sys.path` and imports by dotted name: `extensions: [./adapters/sqlite.py]` and a resources
    module saying `from adapters.sqlite import sqlite` then reach one module object, not two.
    """
    if not path.is_file():
        raise SuiteError(f"{path}: the manifest names this file, and it is not there")

    root = root.resolve()
    # Always to the front, never merely present: a second suite loaded in the same process must
    # win over the first, and then the first must win again if it is reloaded.
    if str(root) in sys.path:
        sys.path.remove(str(root))
    sys.path.insert(0, str(root))

    name = _module_name(path, root)
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

    `sys.modules` is keyed by dotted name, and a dotted name is only unique inside one suite root.
    Two suites both holding a `resources.py` therefore collide, and the second silently gets the
    first one's declarations. Anything loading more than one suite in a process meets this: the
    editor, a tool comparing two suites, and ATF's own tests.
    """
    cached = sys.modules.get(name)
    if cached is None or getattr(cached, "__file__", None) == str(path):
        return
    for cached_name in [n for n in sys.modules if n == name or n.startswith(f"{name}.")]:
        del sys.modules[cached_name]


def _module_name(path: Path, root: Path) -> str:
    """The dotted name this file has when the suite root is on the path."""
    try:
        relative = path.resolve().relative_to(root)
    except ValueError:
        raise SuiteError(
            f"{path}: sits outside {root}, and a manifest names files inside the suite it describes"
        ) from None
    parts = relative.with_suffix("").parts
    bad = [part for part in parts if not re.fullmatch(r"[A-Za-z_]\w*", part)]
    if bad:
        raise SuiteError(f"{path}: {', '.join(bad)} is not importable as a Python module name")
    return ".".join(parts)
