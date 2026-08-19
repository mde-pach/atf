"""`Process` — a running process, recognised by the command line it was started as."""

from __future__ import annotations

import shlex
import socket
import subprocess
import time

from typing_extensions import override

from .. import lives
from ..declare import DriverProperty, Resource, Unreachable, register_system
from ..spi import Payload
from .command import Shell


class Process(Resource):
    """Processes started from one working directory."""

    #: A process is the command line it was started as. There is no second way to recognise one.
    command: Resource.Key[str]
    #: A process that serves one waits for it before it counts as made. Without this, whatever
    #: depends on the process races it — and a race is a test that passes on a fast machine.
    port: int = 0

    shell = DriverProperty[Shell]("shell")

    def _answers(self, port: int) -> bool:
        with socket.socket() as probe:
            probe.settimeout(0.2)
            return probe.connect_ex(("127.0.0.1", port)) == 0

    def _wait_for(self, handle: subprocess.Popen[bytes]) -> None:
        """Block until the declared port answers, or say why it never did.

        A process that serves a port is not *made* until the port is open. Returning before that is
        how a scenario ends up racing the thing it just started — which passes on a fast machine and
        fails on the next run, which is the worst way for a suite to be wrong.
        """
        if not self.port:
            return
        deadline = time.monotonic() + self.shell.start_timeout
        while time.monotonic() < deadline:
            if handle.poll() is not None:
                raise Unreachable(f"the process exited with {handle.returncode} before {self.port} answered")
            if self._answers(self.port):
                return
            time.sleep(0.05)
        raise Unreachable(f"port {self.port} did not answer within {self.shell.start_timeout:g}s")

    def check(self) -> str:
        """Why this declaration cannot be honoured, or nothing.

        Living `forever` means outliving the process that made it, and without a port this system
        has no way to tell whether it did.
        """
        if lives.of(self) == lives.FOREVER and not self.port:
            return (
                f"{type(self).__name__} lives forever and declares no port. A process is recognised "
                f"by the port it answers on; without one, a process an earlier run started cannot be "
                f"told from one that is gone. Declare a port, or let some scenario change it so "
                f"that it lives for the test."
            )
        return ""

    @override
    def find(self) -> Payload | None:
        """Whether this process is running.

        **A declared port is observed; a bare command is only remembered.** With a port,
        recognition is the port answering, so a server an earlier run started is recognised. With
        none, this reads the handles this driver started, and `check` refuses `forever`.
        """
        handle = self.shell.running.get(self.command)
        if self.port:
            if not self._answers(self.port):
                return None
            pid = handle.pid if handle is not None and handle.poll() is None else 0
            return {"command": self.command, "pid": pid, "port": self.port, "running": True}
        if handle is None or handle.poll() is not None:
            return None
        return {"command": self.command, "pid": handle.pid, "port": 0, "running": True}

    @override
    def create(self) -> Payload:
        try:
            handle = subprocess.Popen(
                shlex.split(self.command),
                cwd=self.shell.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise Unreachable(f"{self.command}: {exc}") from exc
        self.shell.running[self.command] = handle
        if handle.poll() is not None:
            raise Unreachable(f"{self.command}: exited immediately with {handle.returncode}")
        self._wait_for(handle)
        return {"command": self.command, "pid": handle.pid, "port": self.port, "running": True}

    @override
    def update(self, changes: Payload) -> Payload:
        """A process is not edited in place: what it was started with is what it is running.

        The declaration changed, so the thing to reconcile is the process itself — stop it, and
        start one that matches.
        """
        self.delete()
        return self.create()

    @override
    def delete(self) -> None:
        handle = self.shell.running.pop(self.command, None)
        if handle is None or handle.poll() is not None:
            return
        handle.terminate()
        try:
            handle.wait(timeout=5)
        except subprocess.TimeoutExpired:
            handle.kill()
            handle.wait(timeout=5)


register_system(Process, Shell, "process")
