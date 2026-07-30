"""Running a command line: what it was asked, and what came back."""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..model.catalog import Node
from . import Context, NoopDelete, Record

# What a node may say about the invocation. The command line is the whole of it; `cwd` and `env` are
# where it stands and what it can see, and both may also be settled once for the environment.
COMMAND, CWD, ENV = "command", "cwd", "env"

DEFAULT_TIMEOUT = 300.0


@dataclass
class CommandAdapter(NoopDelete):
    """The `command` system: run something, and keep what it said."""

    cwd: str = ""
    env: dict[str, str] = field(default_factory=dict)
    timeout: float = DEFAULT_TIMEOUT
    # Whether the environment this runs in starts from the one ATF is running in. A suite driving a
    # tool usually wants PATH and HOME; one pinning an exact environment wants neither.
    inherit_env: bool = True

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> CommandAdapter:
        return cls(
            cwd=str(settings.get("cwd", "")),
            env={str(key): str(value) for key, value in (settings.get("env") or {}).items()},
            timeout=float(settings.get("timeout", DEFAULT_TIMEOUT)),
            inherit_env=bool(settings.get("inherit_env", True)),
        )

    # ---- SPI ----------------------------------------------------------------

    def find(self, node: Node, ctx: Context) -> Record | None:
        """Nothing. A command is an invocation, and an invocation is never already there."""
        return None

    def create(self, node: Node, body: Record, ctx: Context) -> Record:
        """Run what this node says to run. A command exists by having been run."""
        line = body.get(COMMAND)
        if not line:
            raise ValueError(f"{node.id}: nothing to run — give the node a `command` to run")
        return self.run(line, cwd=body.get(CWD), env=body.get(ENV), called=node.id)

    # ---- running one --------------------------------------------------------

    def run(
        self,
        command: Any,
        *,
        cwd: Any = None,
        env: dict[str, str] | None = None,
        called: str = "",
    ) -> Record:
        """Run a command line and hand back everything a scenario could claim about."""
        argv = [str(item) for item in command] if isinstance(command, list | tuple) else _words(command)
        if not argv:
            raise ValueError(f"{called or 'a command'}: there is nothing to run")

        where = Path(str(cwd or self.cwd or Path.cwd()))
        if not where.is_dir():
            raise ValueError(f"{called or ' '.join(argv)}: no directory at {where}")

        environment = {**(os.environ if self.inherit_env else {}), **self.env}
        environment.update({str(key): str(value) for key, value in (env or {}).items()})

        try:
            completed = subprocess.run(
                argv, cwd=where, env=environment, capture_output=True, text=True, timeout=self.timeout
            )
        except FileNotFoundError:
            raise ValueError(f"there is no {argv[0]!r} to run here") from None
        except subprocess.TimeoutExpired:
            raise ValueError(f"{' '.join(argv)} did not finish in {self.timeout:.0f}s") from None

        return {
            "command": " ".join(argv),
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            # Both streams: which one a message came out on is the tool's business and
            # rarely the scenario's.
            "output": completed.stdout + completed.stderr,
            # What "it worked" means for a command, answered once here for every suite's
            # phrasebook. A scenario says it was refused; this says what that is.
            "ok": completed.returncode == 0,
        }


def _words(value: Any) -> list[str]:
    """A command line as a person wrote it, split the way a shell splits it, so quoting works."""
    return shlex.split(str(value)) if value is not None else []
