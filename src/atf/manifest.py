"""`atf.yaml`: one key, `environments`, and what each of them holds."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

MANIFEST_NAME = "atf.yaml"
#: The one directory a suite lives in. Discovered, never registered.
SUITE_DIR = "atf"
KEYS = ("environments",)
ENV_REF_SUFFIX = "_env"

#: Who is responsible for what an environment holds. `atf` may make things here; `them` means ATF
#: may only look, whatever any single resource said.
OWNERS = ("atf", "them")
#: The one key inside an environment that is not a system's settings block, beside `owner`.
INHERITS = "from"


class ManifestError(Exception):
    """Raised when the manifest cannot be found, parsed or read as one."""


@dataclass(frozen=True)
class Environment:
    """One environment: who owns what is in it, and the settings each system reads."""

    name: str
    owner: str = "atf"
    settings: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def mutable(self) -> bool:
        """Whether ATF may make things here — the same fact `owner` states, read as a question."""
        return self.owner == "atf"

    def for_system(self, system: str) -> dict[str, Any] | None:
        """This system's settings here, or nothing when the environment does not configure it."""
        return self.settings.get(system)


@dataclass(frozen=True)
class Manifest:
    """A suite, as its manifest describes it, and the directory the rest of it was found in."""

    path: Path
    root: Path
    environments: dict[str, Environment]

    @property
    def suite(self) -> Path:
        """Where the suite is: `atf/` beside the manifest. Nothing registers it."""
        return self.root / SUITE_DIR

    @property
    def specs(self) -> Path:
        """Where the scenarios are. The same directory — a suite is one flat namespace."""
        return self.suite

    @property
    def default_env(self) -> str:
        """The first environment written. Order in the file is the answer, so nothing repeats it."""
        return next(iter(self.environments), "")

    def env(self, name: str = "") -> Environment:
        """One environment by name, defaulting to `ATF_ENV`, then to the first one written."""
        wanted = name or os.environ.get("ATF_ENV") or self.default_env
        try:
            return self.environments[wanted]
        except KeyError:
            known = ", ".join(self.environments) or "none"
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
            problems.append(
                f"{key}: not a manifest key; the only one is {', '.join(KEYS)}. "
                f"ATF finds {SUITE_DIR}/ beside this file, so nothing points at a path."
            )

    environments = _environments(raw.get("environments"), problems)

    if problems:
        raise ManifestError(f"{path}: invalid manifest:\n  - " + "\n  - ".join(problems))

    return Manifest(path=path, root=root, environments=environments)


def _environments(value: Any, problems: list[str]) -> dict[str, Environment]:
    """Every environment, each resolved against the one it says it comes `from`.

    An environment may only come `from` one already written above it.
    """
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
        base = _base(str(name), entry, out, value, problems)
        owner = entry.get("owner", base.owner if base else "atf")
        if owner not in OWNERS:
            problems.append(
                f"environments.{name}.owner: {owner!r}; it is "
                f"{' or '.join(repr(one) for one in OWNERS)} — who may make what is in here"
            )
            owner = "atf"
        settings: dict[str, dict[str, Any]] = dict(base.settings) if base else {}
        for system, block in entry.items():
            if system in ("owner", INHERITS):
                continue
            block = block or {}
            if not isinstance(block, dict):
                problems.append(f"environments.{name}.{system}: a mapping of setting to value")
                continue
            merged = {**settings.get(str(system), {}), **block}
            settings[str(system)] = resolve_env_refs(merged, f"environments.{name}.{system}")
        out[str(name)] = Environment(name=str(name), owner=str(owner), settings=settings)
    return out


def _base(
    name: str,
    entry: dict[str, Any],
    done: dict[str, Environment],
    everything: dict[str, Any],
    problems: list[str],
) -> Environment | None:
    """The environment this one says it comes `from`, which must already have been read."""
    inherits = entry.get(INHERITS)
    if inherits is None:
        return None
    if not isinstance(inherits, str):
        problems.append(f"environments.{name}.{INHERITS}: the name of another environment")
        return None
    if inherits == name:
        problems.append(f"environments.{name}.{INHERITS}: an environment cannot come from itself")
        return None
    if inherits in done:
        return done[inherits]
    if inherits in everything:
        problems.append(
            f"environments.{name}.{INHERITS}: {inherits!r} is written below this one — "
            f"an environment comes from one already written"
        )
    else:
        known = ", ".join(everything) or "none"
        problems.append(f"environments.{name}.{INHERITS}: no environment {inherits!r} (known: {known})")
    return None


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
