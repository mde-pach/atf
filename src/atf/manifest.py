"""`atf.yaml`: five top-level keys, and the environments under them."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

MANIFEST_NAME = "atf.yaml"
KEYS = ("resources", "specs", "extensions", "default_env", "environments")
ENV_REF_SUFFIX = "_env"


class ManifestError(Exception):
    """Raised when the manifest cannot be found, parsed or read as one."""


@dataclass(frozen=True)
class Environment:
    """One environment: whether ATF may change it, and the settings each system reads."""

    name: str
    mutable: bool = False
    settings: dict[str, dict[str, Any]] = field(default_factory=dict)

    def for_system(self, system: str) -> dict[str, Any] | None:
        """This system's settings here, or nothing when the environment does not configure it."""
        return self.settings.get(system)


@dataclass(frozen=True)
class Manifest:
    """A suite, as its manifest describes it. Paths are resolved against the manifest's directory."""

    path: Path
    root: Path
    resources: tuple[Path, ...]
    specs: Path
    extensions: tuple[Path, ...]
    default_env: str
    environments: dict[str, Environment]

    def env(self, name: str = "") -> Environment:
        """One environment by name, defaulting to `ATF_ENV`, then to the manifest's own default."""
        wanted = name or os.environ.get("ATF_ENV") or self.default_env
        try:
            return self.environments[wanted]
        except KeyError:
            known = ", ".join(sorted(self.environments)) or "none"
            raise ManifestError(f"unknown environment {wanted!r} (known: {known})") from None


def find(start: Path | None = None) -> Path:
    """The nearest `atf.yaml`, from here upwards, or what `ATF_MANIFEST` points at."""
    override = os.environ.get("ATF_MANIFEST")
    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            raise ManifestError(f"ATF_MANIFEST points at {path}, which does not exist")
        return path.resolve()

    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / MANIFEST_NAME
        if candidate.is_file():
            return candidate
    raise ManifestError(
        f"no {MANIFEST_NAME} found in {here} or any parent directory; run `atf init` to start one"
    )


def load(path: Path | None = None) -> Manifest:
    """Read the manifest, reporting everything wrong with it at once."""
    path = (path or find()).resolve()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ManifestError(f"{path}: invalid YAML: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ManifestError(f"{path}: a manifest is a mapping")

    problems: list[str] = []
    root = path.parent

    for key in raw:
        if key not in KEYS:
            problems.append(f"{key}: not a manifest key; they are {', '.join(KEYS)}")

    resources = _paths(raw.get("resources"), "resources", root, problems)
    if not resources:
        problems.append("resources: required — the module(s) that declare what the suite needs")
    extensions = _paths(raw.get("extensions"), "extensions", root, problems)

    specs_raw = raw.get("specs", "./specs")
    if not isinstance(specs_raw, str):
        problems.append("specs: a path to the directory holding the feature files")
        specs_raw = "./specs"
    specs = (root / specs_raw).resolve()

    default_env = raw.get("default_env")
    if not isinstance(default_env, str) or not default_env:
        problems.append("default_env: required, and a non-empty string")
        default_env = ""

    environments = _environments(raw.get("environments"), problems)
    if default_env and environments and default_env not in environments:
        problems.append(f"default_env: {default_env!r} has no entry under environments")

    if problems:
        raise ManifestError(f"{path}: invalid manifest:\n  - " + "\n  - ".join(problems))

    return Manifest(
        path=path,
        root=root,
        resources=resources,
        specs=specs,
        extensions=extensions,
        default_env=default_env,
        environments=environments,
    )


def _paths(value: Any, key: str, root: Path, problems: list[str]) -> tuple[Path, ...]:
    if value is None:
        return ()
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        problems.append(f"{key}: a path, or a list of them")
        return ()
    return tuple((root / item).resolve() for item in items)


def _environments(value: Any, problems: list[str]) -> dict[str, Environment]:
    if value is None:
        problems.append("environments: required, and a mapping of name to what that environment holds")
        return {}
    if not isinstance(value, dict):
        problems.append("environments: a mapping of name to what that environment holds")
        return {}

    out: dict[str, Environment] = {}
    for name, entry in value.items():
        entry = entry or {}
        if not isinstance(entry, dict):
            problems.append(f"environments.{name}: a mapping")
            continue
        mutable = entry.get("mutable", False)
        if not isinstance(mutable, bool):
            problems.append(f"environments.{name}.mutable: true or false; it is false unless stated")
            mutable = False
        settings: dict[str, dict[str, Any]] = {}
        for system, block in entry.items():
            if system == "mutable":
                continue
            block = block or {}
            if not isinstance(block, dict):
                problems.append(f"environments.{name}.{system}: a mapping of setting to value")
                continue
            settings[str(system)] = resolve_env_refs(dict(block), f"environments.{name}.{system}")
        out[str(name)] = Environment(name=str(name), mutable=mutable, settings=settings)
    return out


def resolve_env_refs(value: Any, where: str = "") -> Any:
    """Replace `<key>_env: VAR_NAME` with `<key>: <os.environ[VAR_NAME]>`.

    A secret never appears as a literal in the manifest, and this is the one place one is read.
    `where` is the manifest path of `value`, so a missing variable can name the key that wants it.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            path = f"{where}.{key}" if where else str(key)
            if isinstance(key, str) and key.endswith(ENV_REF_SUFFIX) and isinstance(item, str):
                out[key[: -len(ENV_REF_SUFFIX)]] = _read_env(item, path)
            else:
                out[key] = resolve_env_refs(item, path)
        return out
    if isinstance(value, list):
        return [resolve_env_refs(item, f"{where}[{index}]") for index, item in enumerate(value)]
    return value


def _read_env(var: str, key: str) -> str:
    try:
        return os.environ[var]
    except KeyError:
        raise ManifestError(
            f"{key}: environment variable {var} is not set.\n"
            f"  The manifest points at it instead of storing the value. Export it first:\n"
            f"    export {var}=..."
        ) from None
