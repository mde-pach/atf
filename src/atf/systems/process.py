"""`@process(...)` — a running process, arranged.

Its setting is `cwd`, and its option is `command`. A process resource is *present* when something
it started is still running, and creating one starts it.

```python
from atf import process


@process(command="python -m http.server 8123", unique_by="command")
class Server:
    pass


server = Server()
```

**Recognition here is a live question, as everywhere else.** ATF does not write down a process id;
it asks whether a process matching the declaration is running, so a server killed by hand is absent
the next time anything asks. That is done by holding the handles this adapter started and checking
whether they are still alive — which means a process started by a *previous* run is not recognised,
and this is the one system where `persistent` does not survive the process that made it.
"""

from __future__ import annotations

import shlex
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, TypedDict

from ..declare import Unreachable, adapter, declaration_of, name_of, values_of
from ..spi import Record


@adapter("process")
class Process:
    """Processes started from one working directory."""

    class Options(TypedDict, total=False):
        """What the decorator takes, per resource."""

        command: str
        #: A process that serves one waits for it before it counts as made. Without this, whatever
        #: depends on the process races it — and a race is a test that passes on a fast machine.
        port: int

    class Settings(TypedDict, total=False):
        """What an environment configures."""

        cwd: str
        #: How long to wait for a declared port, in seconds.
        start_timeout: float

    def __init__(self, settings: Settings) -> None:
        self.cwd = Path(settings.get("cwd", ".")).expanduser().resolve()
        self.timeout = float(settings.get("start_timeout", 20))
        self.running: dict[str, subprocess.Popen[bytes]] = {}

    def _port(self, resource: Any) -> int:
        declaration = declaration_of(resource)
        written = values_of(resource).get("port") or declaration.options.get("port")
        return int(written) if written else 0

    def _answers(self, port: int) -> bool:
        with socket.socket() as probe:
            probe.settimeout(0.2)
            return probe.connect_ex(("127.0.0.1", port)) == 0

    def _wait_for(self, resource: Any, handle: subprocess.Popen[bytes]) -> None:
        """Block until the declared port answers, or say why it never did.

        A process that serves a port is not *made* until the port is open. Returning before that is
        how a scenario ends up racing the thing it just started — which passes on a fast machine and
        fails on the next run, which is the worst way for a suite to be wrong.
        """
        port = self._port(resource)
        if not port:
            return
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if handle.poll() is not None:
                raise Unreachable(f"the process exited with {handle.returncode} before {port} answered")
            if self._answers(port):
                return
            time.sleep(0.05)
        raise Unreachable(f"port {port} did not answer within {self.timeout:g}s")

    def _key(self, resource: Any) -> str:
        return name_of(resource) or f"{declaration_of(resource).kind}:{self._command(resource)}"

    def _command(self, resource: Any) -> str:
        declaration = declaration_of(resource)
        written = values_of(resource).get("command") or declaration.options.get("command")
        if not written:
            raise Unreachable(
                f'{declaration.kind}: no command — write it as @process(command="...") or as a field'
            )
        return str(written)

    def find(self, resource: Any) -> Record | None:
        handle = self.running.get(self._key(resource))
        if handle is None or handle.poll() is not None:
            return None
        port = self._port(resource)
        if port and not self._answers(port):
            return None
        return {"command": self._command(resource), "pid": handle.pid, "port": port, "running": True}

    def create(self, resource: Any) -> Record:
        command = self._command(resource)
        try:
            handle = subprocess.Popen(  # noqa: S603 - the command is the declaration; running it is the point
                shlex.split(command),
                cwd=self.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise Unreachable(f"{command}: {exc}") from exc
        self.running[self._key(resource)] = handle
        if handle.poll() is not None:
            raise Unreachable(f"{command}: exited immediately with {handle.returncode}")
        self._wait_for(resource, handle)
        return {"command": command, "pid": handle.pid, "port": self._port(resource), "running": True}

    def update(self, resource: Any, found: Record, changes: Record) -> Record:
        """A process is not edited in place: what it was started with is what it is running.

        The declaration changed, so the thing to reconcile is the process itself — stop it, and
        start one that matches.
        """
        self.delete(resource, found)
        return self.create(resource)

    def delete(self, resource: Any, found: Record) -> None:
        handle = self.running.pop(self._key(resource), None)
        if handle is None or handle.poll() is not None:
            return
        handle.terminate()
        try:
            handle.wait(timeout=5)
        except subprocess.TimeoutExpired:
            handle.kill()
            handle.wait(timeout=5)
