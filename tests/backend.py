"""The environment this suite runs against, and how it gets started.

    uv run python -m tests.backend        # serve it, until you stop it

The suites under test declare `owner`, `todo_list` and `guest` as `rest` resources, so provisioning
one is a real HTTP call and something has to answer it. That something is
[`stub_backend`](stub_backend.py): three JSON collections on loopback. It is not a fact about ATF —
this repository's own catalog is mostly *not* HTTP, and the reference project the Python tests drive
keeps its resources in a file — it is a fact about those particular suite templates.

**Started, not conjured.** It used to come up as an import side effect of `conftest.py`, which
mutated the environment so that a `*_env` pointer in the manifest would resolve. That was a
workaround for the pointer, not a design: a pointer is read when the plugin imports, so the value had
to exist before anything ran. The manifest now writes the address down, which means the server only
has to be answering by the time a scenario asks for a resource — late enough for an ordinary session
fixture, and late enough for you to start it by hand.

So there are two ways in, and they are the two a real project has:

- **Running the scenarios**, where a session fixture starts it if nothing is there. A test run should
  need one command.
- **Running the `atf` command** — `atf status local`, `atf serve`, `atf seed local` — where you start
  it yourself, exactly as you would start the API of the project you were testing.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import yaml

HERE = Path(__file__).parent

if str(HERE) not in sys.path:  # pragma: no cover - only for `python tests/backend.py`
    sys.path.insert(0, str(HERE))

from stub_backend import StubBackend  # noqa: E402 - importable once the line above has run

# Read from the manifest rather than repeated here. Two spellings of one address is how the tests and
# the command end up talking to different servers, and the manifest is the one a reader will check.
MANIFEST = HERE.parent / "atf.yaml"


def configured() -> tuple[str, int, str]:
    """Where the manifest says the environment is, and who it says we are."""
    settings = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["environments"]["local"]["adapters"]["rest"]
    url = str(settings["base_url"])
    return url, urlsplit(url).port or 80, str(settings["auth"]["value"])


def answering(url: str) -> bool:
    """Whether something is already there. Starting a second one would bind nothing and serve less."""
    try:
        httpx.get(url, timeout=1.0)
    except httpx.HTTPError:
        return False
    return True


def start_if_absent() -> StubBackend | None:
    """The backend, started here, or nothing where something is already answering.

    Returning nothing is not a failure: a developer who left `python -m tests.backend` running in
    another terminal is exactly the case this is for, and taking their server away to start our own
    would be worse than useless.
    """
    url, port, actor = configured()
    if answering(url):
        return None
    backend = StubBackend(actor=actor)
    backend.start(port=port)
    return backend


def main() -> int:
    url, port, actor = configured()
    if answering(url):
        print(f"Something is already answering at {url} — nothing to do.")
        return 0
    StubBackend(actor=actor).start(port=port)
    print(f"Serving the stub environment at {url} as {actor!r}. Ctrl-C to stop.")
    try:
        # The server runs in a daemon thread, so this is what keeps the process alive.
        while True:
            import time

            time.sleep(3600)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
