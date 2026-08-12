"""`atf init`: what is already here, what gets written, and the first run of it."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: What is worth looking for, and what each one means. Order is the order they are reported in.
LOOKED_FOR = (
    ("docker-compose.yml", "a compose file"),
    ("docker-compose.yaml", "a compose file"),
    ("compose.yaml", "a compose file"),
    (".env", "an .env"),
    ("Makefile", "a Makefile"),
    ("package.json", "a package.json"),
    ("pyproject.toml", "a pyproject.toml"),
)

#: Environment variables a database url is commonly written to.
URL_VARIABLES = ("DATABASE_URL", "POSTGRES_URL", "MYSQL_URL", "ATF_DATABASE_URL")


@dataclass
class Found:
    """What was already here, and what the scaffold writes from it."""

    notes: list[str] = field(default_factory=list)
    #: A database this project already points at, if one was written down.
    url: str = ""
    #: A command on the path worth putting in front of `When I run "…"`.
    command: str = ""

    @property
    def has_database(self) -> bool:
        return bool(self.url)


def look_around(root: Path) -> Found:
    """What is already here: a compose file, an `.env`, a database url, a command on the path."""
    found = Found()
    for name, said in LOOKED_FOR:
        if (root / name).is_file():
            found.notes.append(f"{said} ({name})")

    found.url = _database_url(root)
    if found.url:
        found.notes.append(f"a database url ({_hidden(found.url)})")

    found.command = _command(root)
    if found.command:
        found.notes.append(f"{found.command} on the path")

    if not found.notes:
        found.notes.append("nothing already here — the scaffold declares a file, which always works")
    return found


def _database_url(root: Path) -> str:
    """A url from the environment, then from a `.env`. Never a guess at one."""
    for name in URL_VARIABLES:
        if os.environ.get(name):
            return str(os.environ[name])
    dotenv = root / ".env"
    if not dotenv.is_file():
        return ""
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        name, _, value = line.strip().partition("=")
        if name.strip() in URL_VARIABLES and value.strip():
            return value.strip().strip("\"'")
    return ""


def _hidden(url: str) -> str:
    """A url with its password replaced by `***`."""
    before, at, after = url.rpartition("@")
    if not at:
        return url
    scheme, _, rest = before.partition("://")
    user = rest.partition(":")[0]
    return f"{scheme}://{user}:***@{after}"


def _command(root: Path) -> str:
    """A command this project probably drives, if one is on the path under its own name."""
    name = root.name.replace("_", "-")
    return name if shutil.which(name) else ""


def manifest_for(found: Found, env: str) -> str:
    """The manifest. Two keys, and one of them is a name."""
    lines = [
        "environments:",
        f"  {env}:",
        "    # ATF may make things here. `them` means it may only look.",
        "    owner: atf",
    ]
    if found.has_database:
        lines.append(f"    sql:   {{ url: {found.url} }}")
    lines.append("    filesystem: { root: . }")
    lines.append(f"    shell: {{ prefix: \"{found.command}\" }}" if found.command else "    shell: { prefix: \"\" }")
    return "\n".join(lines) + "\n"


THINGS = '''\
"""The nouns.

A domain class with one framework word in it. `needs()` says how to get one when nobody gave one —
which is what a default *is*, and why it earns the default slot. Nothing else here belongs to ATF.
"""

from atf import filesystem, needs


@filesystem.file()
class Note:
    path: str
    text: str = needs(lambda: "written by atf init\\n")


hello = Note(path="atf-hello.txt", text="hello from atf\\n")
'''

FEATURE = """\
Feature: the suite runs

  Scenario: a declared file is there before the test
    Given the note "hello"
    Then the note "hello" text is "hello from atf\\n"
"""


def init(root: Path, *, env: str = "local", force: bool = False, found: Found | None = None) -> list[Path]:
    """Write the manifest and the one directory a suite lives in."""
    found = found or look_around(root)
    manifest = root / "atf.yaml"
    if manifest.exists() and not force:
        raise FileExistsError(f"{manifest} already exists; pass --force to overwrite it")

    written: list[Path] = []
    manifest.write_text(manifest_for(found, env), encoding="utf-8")
    written.append(manifest)

    suite = root / "atf"
    suite.mkdir(exist_ok=True)

    for name, body in (("things.py", THINGS), ("hello.feature", FEATURE)):
        path = suite / name
        if not path.exists() or force:
            path.write_text(body, encoding="utf-8")
            written.append(path)
    return written


def first_run(root: Path) -> tuple[bool, list[str]]:
    """Run what was just written, and say what happened.

    The scaffold ends green, or it says plainly that it did not.
    """
    try:
        finished = subprocess.run(
            [sys.executable, "-m", "atf", "run"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, ["", f"could not run the scenario it wrote: {exc}"]

    said = (finished.stdout or finished.stderr).strip().splitlines()
    if finished.returncode == 0:
        return True, ["", *said, "", "green. Write the next scenario in atf/hello.feature."]
    return False, ["", *said, "", "not green yet — `atf plan` says what is missing."]
