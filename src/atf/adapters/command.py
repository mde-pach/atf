"""Running a command line: what it was asked, and what came back.

```gherkin
When I run "atf seed local"
Then the command succeeded
```

Every suite that drives a command-line program was writing the same hundred lines — build an argv,
put the right things in the environment, pick a working directory, run it, keep the exit code and
both streams, and decide what "it failed" means. That is not domain knowledge. It is the shape of a
class of system, the same way a status code and a body are the shape of a JSON API, and it belongs
here for the same reason `rest` does.

**A command line is one string**, because that is how a person writes one. `atf seed local` is what
someone would type and what a reader recognises; a program plus a list of arguments to append to it
is a thing they would have to be taught. It is split the way a shell splits it, so quoting works.

**`ok` is the point.** "How do you know it failed?" is a question about *commands*, not about any
one project, and answering it here is what stops every suite from having to know that `2` means
refused. A scenario says it was refused; the adapter says what that means.

The record is `command`, `exit_code`, `stdout`, `stderr`, `output` — both streams, because which one
a message came out on is the tool's business and rarely the scenario's — and `ok`.

**What a command resource is: one invocation.** `find` answers nothing, because a command is never
*already* run, so a node of this system is `lifecycle: ephemeral` and its body says what to run:

```yaml
seed:
  system: command
  lifecycle: ephemeral
  body:
    command: atf seed local
```

Most suites need no such node. `When I run "…"` says the whole thing in the sentence, and that is
the form to reach for; a node is for a command some *other* resource depends on having been run.

Nothing here decides what a *domain* action is. `When the developer seeds "local"` is still a
suite's own wording over its own step — this only takes away the subprocess.
"""

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
            # Both streams, because which one a message came out on is the tool's business and
            # rarely the scenario's.
            "output": completed.stdout + completed.stderr,
            # What "it worked" means for a command, answered once here instead of in every suite's
            # phrasebook. A scenario says it was refused; this says what that is.
            "ok": completed.returncode == 0,
        }


def _words(value: Any) -> list[str]:
    """A command line as a person wrote it, split the way a shell splits it, so quoting works."""
    return shlex.split(str(value)) if value is not None else []
