"""`@shell.process(...)` — a running process, recognised by the port it answers on."""

from __future__ import annotations

import shlex
import socket
import subprocess
import time
from typing import TypedDict

from ..declare import Unreachable, adapter
from ..spi import Record, Resource
from .command import Shell


@adapter("process", driver="shell")
class Process:
    """Processes started from one working directory."""

    #: A process is the command line it was started as. There is no second way to recognise one.
    recognised_by = ("command",)

    class Options(TypedDict, total=False):
        """What the decorator takes, per resource."""

        command: str
        #: A process that serves one waits for it before it counts as made. Without this, whatever
        #: depends on the process races it — and a race is a test that passes on a fast machine.
        port: int

    def __init__(self, shell: Shell) -> None:
        self.cwd = shell.cwd
        self.timeout = shell.start_timeout
        self.running: dict[str, subprocess.Popen[bytes]] = {}

    def _port(self, resource: Resource) -> int:
        written = resource.values.get("port") or resource.options.get("port")
        return int(written) if written else 0

    def _answers(self, port: int) -> bool:
        with socket.socket() as probe:
            probe.settimeout(0.2)
            return probe.connect_ex(("127.0.0.1", port)) == 0

    def _wait_for(self, resource: Resource, handle: subprocess.Popen[bytes]) -> None:
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

    def check(self, resource: Resource) -> str:
        """Why this declaration cannot be honoured, or nothing.

        Living `forever` means outliving the process that made it, and without a port this system
        has no way to tell whether it did.
        """
        if resource.lives == "forever" and not self._port(resource):
            return (
                f"{resource.kind} lives forever and declares no port. A process is recognised by "
                f"the port it answers on; without one, a process an earlier run started cannot be "
                f"told from one that is gone. Declare a port, or let some scenario change it so "
                f"that it lives for the test."
            )
        return ""

    def _key(self, resource: Resource) -> str:
        return resource.name or f"{resource.kind}:{self._command(resource)}"

    def _command(self, resource: Resource) -> str:
        written = resource.values.get("command") or resource.options.get("command")
        if not written:
            raise Unreachable(
                f'{resource.kind}: no command — write it as @process(command="...") or as a field'
            )
        return str(written)

    def find(self, resource: Resource) -> Record | None:
        """Whether this process is running.

        **A declared port is observed; a bare command is only remembered.** With a port,
        recognition is the port answering, so a server an earlier run started is recognised. With
        none, this reads the handles this adapter started, and `check` refuses `persistent`.
        """
        port = self._port(resource)
        handle = self.running.get(self._key(resource))
        if port:
            if not self._answers(port):
                return None
            pid = handle.pid if handle is not None and handle.poll() is None else 0
            return {"command": self._command(resource), "pid": pid, "port": port, "running": True}
        if handle is None or handle.poll() is not None:
            return None
        return {"command": self._command(resource), "pid": handle.pid, "port": 0, "running": True}

    def create(self, resource: Resource) -> Record:
        command = self._command(resource)
        try:
            handle = subprocess.Popen(
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

    def update(self, resource: Resource, found: Record, changes: Record) -> Record:
        """A process is not edited in place: what it was started with is what it is running.

        The declaration changed, so the thing to reconcile is the process itself — stop it, and
        start one that matches.
        """
        self.delete(resource, found)
        return self.create(resource)

    def delete(self, resource: Resource, found: Record) -> None:
        handle = self.running.pop(self._key(resource), None)
        if handle is None or handle.poll() is not None:
            return
        handle.terminate()
        try:
            handle.wait(timeout=5)
        except subprocess.TimeoutExpired:
            handle.kill()
            handle.wait(timeout=5)
