r"""`@file`, `@directory` and `@tree` — three things under one root, configured once."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TypedDict

from ..declare import Unreachable, adapter, driver
from ..spi import Record, Resource


@driver("filesystem")
class Filesystem:
    """One root, and everything the three adapters over it need to reach inside it."""

    class Settings(TypedDict):
        """What an environment configures, once, for all three."""

        root: str

    def __init__(self, settings: Settings) -> None:
        self.root = Path(settings["root"]).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)


class Options(TypedDict, total=False):
    """What the decorator takes, per resource."""

    path: str


class Under:
    """What the three share: a root, and one path inside it."""

    Options = Options
    #: A thing under a root is its path. There is no second way to recognise one.
    recognised_by = ("path",)

    def __init__(self, filesystem: Filesystem) -> None:
        self.root = filesystem.root

    def path(self, resource: Resource) -> Path:
        written = resource.values.get("path") or resource.options.get("path")
        if not written:
            raise Unreachable(f"{resource.kind}: no path — write it as a `path` field")
        candidate = (self.root / str(written)).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise Unreachable(f"{resource.kind}: {written} resolves outside {self.root}")
        return candidate

    def here(self, path: Path) -> str:
        return str(path.relative_to(self.root))

    def browse(self, resource: Resource) -> list[Record]:
        """Everything beside this resource — what `the environment has 2 file` counts."""
        parent = self.path(resource).parent
        if not parent.is_dir():
            return []
        return [
            {"path": self.here(child), "kind": "directory" if child.is_dir() else "file"}
            for child in sorted(parent.iterdir())
        ]


@adapter("file", driver="filesystem")
class File(Under):
    """One file, and the text in it."""

    def find(self, resource: Resource) -> Record | None:
        path = self.path(resource)
        if not path.is_file():
            return None
        try:
            return {"path": self.here(path), "kind": "file", "text": path.read_text(encoding="utf-8")}
        except OSError as exc:
            raise Unreachable(f"{path}: {exc}") from exc

    def create(self, resource: Resource) -> Record:
        path = self.path(resource)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(resource.values.get("text", "")), encoding="utf-8")
        except OSError as exc:
            raise Unreachable(f"{path}: {exc}") from exc
        found = self.find(resource)
        if found is None:
            raise Unreachable(f"{path}: written, and not there afterwards")
        return found

    def update(self, resource: Resource, found: Record, changes: Record) -> Record:
        if "text" in changes:
            path = self.path(resource)
            try:
                path.write_text(str(changes["text"]), encoding="utf-8")
            except OSError as exc:
                raise Unreachable(f"{path}: {exc}") from exc
        return {**found, **changes}

    def delete(self, resource: Resource, found: Record) -> None:
        path = self.path(resource)
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            raise Unreachable(f"{path}: {exc}") from exc


@adapter("directory", driver="filesystem")
class Directory(Under):
    """A directory, and nothing about what is inside it.

    Teardown removes it only when it is empty. A directory whose whole contents are declared is a
    `@tree`.
    """

    def find(self, resource: Resource) -> Record | None:
        path = self.path(resource)
        return {"path": self.here(path), "kind": "directory"} if path.is_dir() else None

    def create(self, resource: Resource) -> Record:
        path = self.path(resource)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise Unreachable(f"{path}: {exc}") from exc
        return {"path": self.here(path), "kind": "directory"}

    def update(self, resource: Resource, found: Record, changes: Record) -> Record:
        """A directory holds nothing to change; its identity is its path."""
        return {**found, **changes}

    def delete(self, resource: Resource, found: Record) -> None:
        path = self.path(resource)
        try:
            if path.is_dir():
                path.rmdir()
        except OSError as exc:
            raise Unreachable(f"{path}: {exc}") from exc


@adapter("tree", driver="filesystem")
class Tree(Under):
    """A directory whose whole contents this resource declares, as `files: {path -> text}`.

    A tree **owns what is under it**: teardown removes the lot, including anything written into it
    while a test ran.
    """

    def _files(self, resource: Resource) -> dict[str, str]:
        files = resource.values.get("files")
        if not isinstance(files, dict):
            raise Unreachable(
                f"{resource.kind}: a tree declares its contents as a `files` field, "
                f"mapping a path inside it to that file's text"
            )
        return {str(k): str(v) for k, v in files.items()}

    def find(self, resource: Resource) -> Record | None:
        path = self.path(resource)
        if not path.is_dir():
            return None
        wanted = self._files(resource)
        missing = [name for name in wanted if not (path / name).is_file()]
        return {"path": self.here(path), "kind": "tree", "files": sorted(set(wanted) - set(missing))}

    def create(self, resource: Resource) -> Record:
        path = self.path(resource)
        try:
            for name, text in self._files(resource).items():
                inside = (path / name).resolve()
                if self.root not in inside.parents:
                    raise Unreachable(f"{name} resolves outside {self.root}")
                inside.parent.mkdir(parents=True, exist_ok=True)
                inside.write_text(text, encoding="utf-8")
        except OSError as exc:
            raise Unreachable(f"{path}: {exc}") from exc
        found = self.find(resource)
        if found is None:
            raise Unreachable(f"{path}: written, and not there afterwards")
        return found

    def update(self, resource: Resource, found: Record, changes: Record) -> Record:
        return {**found, **self.create(resource)}

    def delete(self, resource: Resource, found: Record) -> None:
        shutil.rmtree(self.path(resource), ignore_errors=True)
