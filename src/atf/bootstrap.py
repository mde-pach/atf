"""The single funnel from environment to a configured system (§4.3)."""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters import Adapter, build
from .config import Manifest, load_manifest, resolve_env, resolve_env_refs
from .materializer import Materializer


@dataclass
class Boot:
    manifest: Manifest
    env: str
    materializer: Materializer
    clients: dict[str, dict[str, Any]]


def bootstrap(env: str | None = None, manifest_path: Path | None = None) -> Boot:
    manifest = load_manifest(manifest_path)
    active = env or resolve_env(manifest)
    settings = manifest.env(active)

    load_adapter_modules(manifest)

    adapters: dict[str, Adapter] = {
        system: build(system, resolve_env_refs(raw)) for system, raw in settings.adapters.items()
    }
    clients = {name: resolve_env_refs(raw) for name, raw in settings.clients.items()}

    return Boot(
        manifest=manifest,
        env=active,
        materializer=Materializer(manifest.catalog_dir, active, adapters),
        clients=clients,
    )


def load_adapter_modules(manifest: Manifest) -> None:
    """Import the project's adapter modules for their `register()` side-effects.

    A module that resolves to a file inside the suite is loaded from that path directly, so the
    suite never has to go on `sys.path` — where a file named `types.py` or `json.py` would shadow
    the stdlib for the rest of the process.
    """
    for module in manifest.adapter_modules:
        if module in sys.modules:
            continue
        if _load_from_suite(module, manifest.root):
            continue
        # A module installed as a package, or one living outside the suite.
        root = str(manifest.root)
        if root not in sys.path:
            sys.path.append(root)
        importlib.import_module(module)


def _load_from_suite(module: str, root: Path) -> bool:
    relative = module.replace(".", os.sep)
    for candidate in (root / f"{relative}.py", root / relative / "__init__.py"):
        if not candidate.is_file():
            continue
        spec = importlib.util.spec_from_file_location(module, candidate)
        if spec is None or spec.loader is None:
            continue
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[module] = loaded
        try:
            spec.loader.exec_module(loaded)
        except Exception:
            del sys.modules[module]
            raise
        return True
    return False
