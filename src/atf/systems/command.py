"""`shell` — running things on this machine: a command line, or a long-lived process."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any, TypedDict

from ..declare import Unreachable, driver
from ..spi import Record
from ..steps import act, check


def run(prefix: str, command: str, cwd: Path | None = None) -> Record:
    """Run one command line through an environment's prefix, and report what it did."""
    line = f"{prefix} {command}".strip() if prefix else command
    try:
        finished = subprocess.run(
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


@driver("shell")
class Shell:
    """Command lines run through one environment's prefix, and processes started from its `cwd`.

    A command line is not a resource: it is something a test *does*, and what it produced lands in a
    slot. A step, a pytest function and an adapter all ask for this by the name `shell`.
    """

    class Settings(TypedDict, total=False):
        """What an environment configures."""

        #: Put in front of every command a test runs.
        prefix: str
        #: Where a command runs, and where a `shell.process` is started.
        cwd: str
        #: How long a `shell.process` waits for a declared port, in seconds.
        start_timeout: float

    def __init__(self, settings: Settings) -> None:
        self.prefix = settings.get("prefix", "")
        self.cwd = Path(settings.get("cwd", ".")).expanduser().resolve()
        self.start_timeout = float(settings.get("start_timeout", 20))

    def __call__(self, command: str) -> Record:
        """`shell("todo list")` — what a Python test and `When I run` both reach."""
        return run(self.prefix, command, self.cwd)


# --- The words this system brings ------------------------------------------------------------------
#
# A system brings its things, and the words for them. Running something is not a concept in ATF's
# model; it is the shell system's word, met the first time somebody tests a command line.


@act('I run "{command}"')
def _run(command: str, shell: Shell) -> Record:
    """`When I run "todo show primary@example.com"`. What it produced becomes `it`."""
    return shell(command)


@check("the command succeeded")
def _succeeded(atf: Any) -> tuple[bool, str]:
    """It exited zero."""
    result = atf.it()
    code = result.get("exit_code") if isinstance(result, dict) else None
    return code == 0, f"it exited {code}: {str(result.get('output', '')).strip()[:200]}"


@check("the command failed")
def _failed(atf: Any) -> tuple[bool, str]:
    """It exited with anything but zero."""
    result = atf.it()
    code = result.get("exit_code") if isinstance(result, dict) else None
    return bool(code), "it exited 0"
