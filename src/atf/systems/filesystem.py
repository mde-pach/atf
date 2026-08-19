r"""`File`, `Directory` and `Tree` — three things under one root, configured once."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, TypedDict

from typing_extensions import override

from ..declare import Driver, DriverProperty, Resource, Unreachable, register_system
from ..spi import Payload


class Filesystem(Driver):
    """One root, and everything the three resources over it need to reach inside it."""

    class Settings(TypedDict):
        """What an environment configures, once, for all three."""

        root: str

    def __init__(self, settings: Settings) -> None:
        self.root = Path(settings["root"]).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)


class Under(Resource):
    """What the three share: a root, and one path inside it."""

    #: A thing under a root is its path. There is no second way to recognise one.
    path: Resource.Key[str]

    filesystem = DriverProperty[Filesystem]("filesystem")

    def _resolve(self) -> Path:
        written = self.path
        if not written:
            raise Unreachable(f"{type(self).__name__}: no path — write it as a `path` field")
        root = self.filesystem.root
        candidate = (root / str(written)).resolve()
        if candidate != root and root not in candidate.parents:
            raise Unreachable(f"{type(self).__name__}: {written} resolves outside {root}")
        return candidate

    def _here(self, path: Path) -> str:
        return str(path.relative_to(self.filesystem.root))

    def browse(self) -> list[Payload]:
        """Everything beside this resource — what `Then there are 2 files` counts."""
        parent = self._resolve().parent
        if not parent.is_dir():
            return []
        return [
            {"path": self._here(child), "kind": "directory" if child.is_dir() else "file"}
            for child in sorted(parent.iterdir())
        ]


class File(Under):
    """One file, and the text in it."""

    text: Any = ""

    @override
    def find(self) -> Payload | None:
        path = self._resolve()
        if not path.is_file():
            return None
        try:
            return {"path": self._here(path), "kind": "file", "text": path.read_text(encoding="utf-8")}
        except OSError as exc:
            raise Unreachable(f"{path}: {exc}") from exc

    @override
    def create(self) -> Payload:
        path = self._resolve()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(self.text), encoding="utf-8")
        except OSError as exc:
            raise Unreachable(f"{path}: {exc}") from exc
        found = self.find()
        if found is None:
            raise Unreachable(f"{path}: written, and not there afterwards")
        return found

    @override
    def update(self, changes: Payload) -> Payload:
        if "text" in changes:
            path = self._resolve()
            try:
                path.write_text(str(changes["text"]), encoding="utf-8")
            except OSError as exc:
                raise Unreachable(f"{path}: {exc}") from exc
        found = self.find()
        if found is None:
            raise Unreachable(f"{self._resolve()}: updated, and not there afterwards")
        return found

    @override
    def delete(self) -> None:
        path = self._resolve()
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            raise Unreachable(f"{path}: {exc}") from exc


class Directory(Under):
    """A directory, and nothing about what is inside it.

    Teardown removes it only when it is empty. A directory whose whole contents are declared is a
    `Tree`.
    """

    @override
    def find(self) -> Payload | None:
        path = self._resolve()
        return {"path": self._here(path), "kind": "directory"} if path.is_dir() else None

    @override
    def create(self) -> Payload:
        path = self._resolve()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise Unreachable(f"{path}: {exc}") from exc
        return {"path": self._here(path), "kind": "directory"}

    @override
    def update(self, changes: Payload) -> Payload:
        """A directory holds nothing to change; its identity is its path."""
        found = self.find() or {}
        return {**found, **changes}

    @override
    def delete(self) -> None:
        path = self._resolve()
        try:
            if path.is_dir():
                path.rmdir()
        except OSError as exc:
            raise Unreachable(f"{path}: {exc}") from exc


class Tree(Under):
    """A directory whose whole contents this resource declares, as `files: {path -> text}`.

    A tree **owns what is under it**: teardown removes the lot, including anything written into it
    while a test ran.
    """

    files: Any = None

    def _wanted(self) -> dict[str, str]:
        if not isinstance(self.files, dict):
            raise Unreachable(
                f"{type(self).__name__}: a tree declares its contents as a `files` field, "
                f"mapping a path inside it to that file's text"
            )
        return {str(k): str(v) for k, v in self.files.items()}

    @override
    def find(self) -> Payload | None:
        path = self._resolve()
        if not path.is_dir():
            return None
        wanted = self._wanted()
        missing = [name for name in wanted if not (path / name).is_file()]
        return {"path": self._here(path), "kind": "tree", "files": sorted(set(wanted) - set(missing))}

    @override
    def create(self) -> Payload:
        path = self._resolve()
        try:
            for name, text in self._wanted().items():
                inside = (path / name).resolve()
                if self.filesystem.root not in inside.parents:
                    raise Unreachable(f"{name} resolves outside {self.filesystem.root}")
                inside.parent.mkdir(parents=True, exist_ok=True)
                inside.write_text(text, encoding="utf-8")
        except OSError as exc:
            raise Unreachable(f"{path}: {exc}") from exc
        found = self.find()
        if found is None:
            raise Unreachable(f"{path}: written, and not there afterwards")
        return found

    @override
    def update(self, changes: Payload) -> Payload:
        return {**self.create(), **changes}

    @override
    def delete(self) -> None:
        shutil.rmtree(self._resolve(), ignore_errors=True)


register_system(File, Filesystem, "file")
register_system(Directory, Filesystem, "directory")
register_system(Tree, Filesystem, "tree")
