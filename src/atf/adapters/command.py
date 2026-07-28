"""A command-line program: what it was asked, and what came back.

Every suite that tests a CLI was writing the same hundred lines — build an argv, put the right
things in the environment, pick a working directory, run it, keep the exit code and both streams,
and decide what "it failed" means. That is not domain knowledge. It is the shape of a class of
system, the same way a status code and a body are the shape of a JSON API, and it belongs here for
the same reason `rest` does.

**What a command resource is: one invocation.** A command is never *already* run, so `find` answers
nothing and `create` runs it — which makes it naturally `lifecycle: ephemeral`, and makes
`Given the command "…"` mean "this has been run". The record is what came back.

```yaml
atf:
  system: command
  lifecycle: ephemeral
  natural_key: args
```

```gherkin
Given the command "atf" but:
  | args | seed local |
Then the command field "ok" is "true"
```

**`ok` is the point.** "How do you know it failed?" is a question about *commands*, not about any one
project, and answering it here is what stops every phrasebook in every suite from having to know
that `2` means refused. A scenario says `it failed`; the adapter says what that means.

Nothing here decides what a *domain* action is. `When the developer seeds "local"` is still a suite's
own wording over its own step — this only takes away the subprocess.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..catalog import Node
from . import Context, NoopDelete, Record

# What a node may say about the invocation. `argv` is the whole of it; `args` is appended to the
# `program` the environment configured, which is what lets one node serve every invocation of one
# tool with `but:`.
ARGV, ARGS, CWD, ENV = "argv", "args", "cwd", "env"

DEFAULT_TIMEOUT = 300.0


@dataclass
class CommandAdapter(NoopDelete):
    """The `command` system: run something, and keep what it said."""

    program: list[str] = field(default_factory=list)
    cwd: str = ""
    env: dict[str, str] = field(default_factory=dict)
    timeout: float = DEFAULT_TIMEOUT
    # Whether the environment this runs in starts from the one ATF is running in. A suite driving a
    # tool usually wants PATH and HOME; one pinning an exact environment wants neither.
    inherit_env: bool = True

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> CommandAdapter:
        return cls(
            program=_words(settings.get("program")),
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
        """Run it, and hand back everything a scenario could want to claim about."""
        argv = self._argv(node, body)
        where = Path(str(body.get(CWD) or self.cwd or Path.cwd()))
        if not where.is_dir():
            raise ValueError(f"{node['id']}: no directory at {where}")

        environment = {**(os.environ if self.inherit_env else {}), **self.env}
        environment.update({str(key): str(value) for key, value in (body.get(ENV) or {}).items()})

        try:
            completed = subprocess.run(
                argv,
                cwd=where,
                env=environment,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except FileNotFoundError:
            raise ValueError(f"{node['id']}: there is no {argv[0]!r} to run here") from None
        except subprocess.TimeoutExpired:
            raise ValueError(f"{node['id']}: {' '.join(argv)} did not finish in {self.timeout:.0f}s") from None

        return {
            "argv": " ".join(argv),
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            # Both streams, because which one a message came out on is the tool's business and
            # rarely the scenario's.
            "output": completed.stdout + completed.stderr,
            # What "it worked" means for a command, answered once here instead of in every suite's
            # phrasebook. A scenario says `it failed`; this says what that is.
            "ok": completed.returncode == 0,
        }

    # ---- internals ----------------------------------------------------------

    def _argv(self, node: Node, body: Record) -> list[str]:
        whole = _words(body.get(ARGV))
        if whole:
            return whole
        argv = [*self.program, *_words(body.get(ARGS))]
        if not argv:
            raise ValueError(
                f"{node['id']}: nothing to run — give the node an `argv`, or an `args` to follow "
                "the `program` this environment configures"
            )
        return argv


def _words(value: Any) -> list[str]:
    """A command line, however it was written: a list of words, or one string to split like a shell."""
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return shlex.split(str(value))
