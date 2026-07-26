"""Manifest resolution, parsing and validation. Every entry point goes through here."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

MANIFEST_NAMES = ("atf.yaml", "atf.toml")
ENV_REF_SUFFIX = "_env"

# Fallback palette for systems without an explicit display colour.
_DEFAULT_COLORS = ("#2f6be0", "#7857d8", "#0f8f6f", "#c2660a", "#b3315f", "#1f7f9c")


class ConfigError(Exception):
    """Raised when the manifest cannot be found, parsed or validated."""


@dataclass(frozen=True)
class SystemDisplay:
    label: str
    color: str


@dataclass(frozen=True)
class DisplayConfig:
    systems: dict[str, SystemDisplay] = field(default_factory=dict)

    def system(self, name: str) -> SystemDisplay:
        known = self.systems.get(name)
        if known is not None:
            return known
        color = _DEFAULT_COLORS[sum(map(ord, name)) % len(_DEFAULT_COLORS)]
        return SystemDisplay(label=name.replace("_", " ").title(), color=color)


@dataclass(frozen=True)
class EnvConfig:
    adapters: dict[str, dict[str, Any]] = field(default_factory=dict)
    clients: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class Manifest:
    root: Path
    path: Path
    catalog_dir: Path
    specs_dir: Path
    default_env: str
    adapter_modules: list[str]
    environments: dict[str, EnvConfig]
    mutable_envs: set[str]
    display: DisplayConfig

    def env(self, name: str) -> EnvConfig:
        try:
            return self.environments[name]
        except KeyError:
            known = ", ".join(sorted(self.environments)) or "none"
            raise ConfigError(f"unknown environment {name!r} (known: {known})") from None

    def is_mutable(self, name: str) -> bool:
        return name in self.mutable_envs


def resolve_manifest(start: Path | None = None) -> Path:
    override = os.environ.get("ATF_MANIFEST")
    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            raise ConfigError(f"ATF_MANIFEST points at {path}, which does not exist")
        return path.resolve()

    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        for name in MANIFEST_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    raise ConfigError(
        f"no atf.yaml found in {here} or any parent directory; "
        "run `atf init` to scaffold a project, or set ATF_MANIFEST"
    )


def resolve_env(manifest: Manifest) -> str:
    return os.environ.get("ATF_ENV") or manifest.default_env


def load_manifest(path: Path | None = None) -> Manifest:
    path = (path or resolve_manifest()).resolve()
    if path.suffix == ".toml":
        raise ConfigError(f"{path.name}: atf.toml is not supported yet; use atf.yaml")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: manifest must be a mapping")

    problems: list[str] = []
    root = path.parent

    def resolved_dir(key: str, default: str) -> Path:
        value = raw.get(key, default)
        if not isinstance(value, str):
            problems.append(f"{key}: must be a path string")
            return root / default
        return (root / value).resolve()

    catalog_dir = resolved_dir("catalog", "./catalog")
    specs_dir = resolved_dir("specs", "./specs")

    default_env = raw.get("default_env")
    if not isinstance(default_env, str) or not default_env:
        problems.append("default_env: required, must be a non-empty string")
        default_env = ""

    adapter_modules = _string_list(raw.get("adapters", []), "adapters", problems)
    mutable_envs = set(_string_list(raw.get("mutable_envs", []), "mutable_envs", problems))

    environments = _parse_environments(raw.get("environments"), problems)
    if default_env and environments and default_env not in environments:
        problems.append(f"default_env: {default_env!r} has no entry under environments")
    unknown_mutable = sorted(mutable_envs - set(environments))
    if environments and unknown_mutable:
        problems.append(f"mutable_envs: unknown environment(s) {', '.join(unknown_mutable)}")

    display = _parse_display(raw.get("display"), problems)

    if problems:
        raise ConfigError(f"{path}: invalid manifest:\n  - " + "\n  - ".join(problems))

    return Manifest(
        root=root,
        path=path,
        catalog_dir=catalog_dir,
        specs_dir=specs_dir,
        default_env=default_env,
        adapter_modules=adapter_modules,
        environments=environments,
        mutable_envs=mutable_envs,
        display=display,
    )


def _string_list(value: Any, key: str, problems: list[str]) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        problems.append(f"{key}: must be a list of strings")
        return []
    return [item for item in value if isinstance(item, str)]


def _parse_environments(value: Any, problems: list[str]) -> dict[str, EnvConfig]:
    if value is None:
        problems.append("environments: required, must be a mapping of env name -> settings")
        return {}
    if not isinstance(value, dict):
        problems.append("environments: must be a mapping of env name -> settings")
        return {}

    out: dict[str, EnvConfig] = {}
    for name, entry in value.items():
        if entry is None:
            entry = {}
        if not isinstance(entry, dict):
            problems.append(f"environments.{name}: must be a mapping")
            continue
        adapters = _mapping_of_mappings(entry.get("adapters"), f"environments.{name}.adapters", problems)
        clients = _mapping_of_mappings(entry.get("clients"), f"environments.{name}.clients", problems)
        out[str(name)] = EnvConfig(adapters=adapters, clients=clients)
    return out


def _mapping_of_mappings(value: Any, key: str, problems: list[str]) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        problems.append(f"{key}: must be a mapping")
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, settings in value.items():
        if settings is None:
            settings = {}
        if not isinstance(settings, dict):
            problems.append(f"{key}.{name}: must be a mapping")
            continue
        out[str(name)] = dict(settings)
    return out


def _parse_display(value: Any, problems: list[str]) -> DisplayConfig:
    if value is None:
        return DisplayConfig()
    if not isinstance(value, dict):
        problems.append("display: must be a mapping")
        return DisplayConfig()
    systems_raw = value.get("systems") or {}
    if not isinstance(systems_raw, dict):
        problems.append("display.systems: must be a mapping")
        return DisplayConfig()

    systems: dict[str, SystemDisplay] = {}
    for name, entry in systems_raw.items():
        if not isinstance(entry, dict):
            problems.append(f"display.systems.{name}: must be a mapping")
            continue
        fallback = DisplayConfig().system(str(name))
        label = entry.get("label", fallback.label)
        color = entry.get("color", fallback.color)
        if not isinstance(label, str) or not isinstance(color, str):
            problems.append(f"display.systems.{name}: label and color must be strings")
            continue
        systems[str(name)] = SystemDisplay(label=label, color=color)
    return DisplayConfig(systems=systems)


def resolve_env_refs(value: Any, where: str = "") -> Any:
    """Replace `<key>_env: VAR_NAME` pointers with `<key>: <os.environ[VAR_NAME]>`.

    Secrets never appear as literals in the manifest; this is the single place they are read.
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
        raise ConfigError(
            f"{key}: environment variable {var} is not set.\n"
            f"  The manifest points at it instead of storing the value. Export it first:\n"
            f"    export {var}=..."
        ) from None
