r"""`@filesystem(...)` — files and directories, arranged.

Its setting is `root`, and its option is `path`. A resource that declares `text` is a file holding
it; one that declares no text is a directory.

```python
from atf import filesystem


@filesystem(path="config/settings.toml", unique_by="path")
class Settings:
    text: str


settings = Settings(text="[server]\\nport = 8080\\n")
```

A path is always resolved inside `root` and never escapes it. A suite that could write to `../..`
is a suite that can delete something it did not make, and teardown here removes what it finds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from ..declare import Unreachable, adapter, declaration_of, values_of
from ..spi import Record


@adapter("filesystem")
class Filesystem:
    """Files and directories under one root."""

    class Options(TypedDict, total=False):
        """What the decorator takes, per resource."""

        path: str

    class Settings(TypedDict):
        """What an environment configures."""

        root: str

    def __init__(self, settings: Settings) -> None:
        self.root = Path(settings["root"]).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, resource: Any) -> Path:
        declaration = declaration_of(resource)
        written = values_of(resource).get("path") or declaration.options.get("path")
        if not written:
            raise Unreachable(
                f'{declaration.kind}: no path — write it as @filesystem(path="...") or as a field'
            )
        candidate = (self.root / str(written)).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise Unreachable(f"{declaration.kind}: {written} resolves outside {self.root}")
        return candidate

    def _is_directory(self, resource: Any) -> bool:
        return "text" not in values_of(resource)

    def _tree(self, resource: Any) -> dict[str, str] | None:
        """A directory whose whole contents this resource declares, as `path -> text`.

        A resource that declares `files` **owns what is under it**. ATF wrote the tree, so ATF
        removes the tree — including anything the thing under test added while the test ran. A
        directory that declares no `files` is only ever removed when it is empty, because removing
        a tree ATF did not populate is not teardown.
        """
        files = values_of(resource).get("files")
        return {str(k): str(v) for k, v in files.items()} if isinstance(files, dict) else None

    def find(self, resource: Any) -> Record | None:
        path = self._path(resource)
        if not path.exists():
            return None
        here = str(path.relative_to(self.root))
        tree = self._tree(resource)
        if tree is not None:
            missing = [name for name in tree if not (path / name).is_file()]
            return {"path": here, "kind": "tree", "files": sorted(set(tree) - set(missing))}
        if path.is_dir():
            return {"path": here, "kind": "directory"}
        try:
            return {"path": here, "kind": "file", "text": path.read_text(encoding="utf-8")}
        except OSError as exc:
            raise Unreachable(f"{path}: {exc}") from exc

    def create(self, resource: Any) -> Record:
        path = self._path(resource)
        tree = self._tree(resource)
        if tree is not None:
            try:
                for name, text in tree.items():
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
        try:
            if self._is_directory(resource):
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(str(values_of(resource).get("text", "")), encoding="utf-8")
        except OSError as exc:
            raise Unreachable(f"{path}: {exc}") from exc
        found = self.find(resource)
        if found is None:
            raise Unreachable(f"{path}: written, and not there afterwards")
        return found

    def update(self, resource: Any, found: Record, changes: Record) -> Record:
        path = self._path(resource)
        if self._tree(resource) is not None:
            return {**found, **self.create(resource)}
        if "text" in changes:
            try:
                path.write_text(str(changes["text"]), encoding="utf-8")
            except OSError as exc:
                raise Unreachable(f"{path}: {exc}") from exc
        return {**found, **changes}

    def delete(self, resource: Any, found: Record) -> None:
        path = self._path(resource)
        if self._tree(resource) is not None:
            import shutil  # noqa: PLC0415

            shutil.rmtree(path, ignore_errors=True)
            return
        try:
            if path.is_dir():
                # Only if it is empty. Removing a tree ATF did not make is not teardown.
                path.rmdir()
            elif path.exists():
                path.unlink()
        except OSError as exc:
            raise Unreachable(f"{path}: {exc}") from exc

    def browse(self, resource: Any) -> list[Record]:
        """Everything beside this resource — what `the environment has 2 file` counts."""
        parent = self._path(resource).parent
        if not parent.is_dir():
            return []
        return [
            {"path": str(child.relative_to(self.root)), "kind": "directory" if child.is_dir() else "file"}
            for child in sorted(parent.iterdir())
        ]
