"""`@command` — a command-line invocation, and the `shell` fixture behind `When I run`."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any, TypedDict

from ..declare import Unreachable, adapter, declaration_of, name_of, values_of
from ..spi import Record


def run(prefix: str, command: str, cwd: Path | None = None) -> Record:
    """Run one command line through an environment's prefix, and report what it did."""
    line = f"{prefix} {command}".strip() if prefix else command
    try:
        finished = subprocess.run(  # noqa: S603 - running the command is what this system is for
            shlex.split(line),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise Unreachable(f"{line}: {exc}") from exc
    output = finished.stdout + finished.stderr
    return {
        "command": line,
        "exit_code": finished.returncode,
        "output": output,
        "ok": finished.returncode == 0,
    }


@adapter("command")
class Command:
    """Command lines run through one environment's prefix."""

    class Options(TypedDict, total=False):
        """What the decorator takes, per resource."""

        run: str

    class Settings(TypedDict, total=False):
        """What an environment configures."""

        prefix: str
        cwd: str

    def __init__(self, settings: Settings) -> None:
        self.prefix = settings.get("prefix", "")
        self.cwd = Path(settings.get("cwd", ".")).expanduser().resolve()
        self.ran: dict[str, Record] = {}

    def _line(self, resource: Any) -> str:
        declaration = declaration_of(resource)
        written = values_of(resource).get("run") or declaration.options.get("run")
        if not written:
            raise Unreachable(f'{declaration.kind}: no command — write it as @command(run="...")')
        return str(written)

    def shell(self, command: str) -> Record:
        """What the `shell` fixture calls, and what `When I run` reaches."""
        return run(self.prefix, command, self.cwd)

    def find(self, resource: Any) -> Record | None:
        return self.ran.get(name_of(resource) or self._line(resource))

    def create(self, resource: Any) -> Record:
        record = self.shell(self._line(resource))
        self.ran[name_of(resource) or self._line(resource)] = record
        if not record["ok"]:
            raise Unreachable(f"{record['command']} exited {record['exit_code']}: {record['output'].strip()}")
        return record

    def update(self, resource: Any, found: Record, changes: Record) -> Record:
        """What a command line did is not edited; it is done again."""
        return self.create(resource)

    def delete(self, resource: Any, found: Record) -> None:
        self.ran.pop(name_of(resource) or self._line(resource), None)
