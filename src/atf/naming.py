"""A short token that is this run's alone, for a factory to build recognition values from."""

from __future__ import annotations

import os
import uuid

#: What a worker, a shard, or a person naming one sets. Read every time, so a subprocess inherits it.
VARIABLE = "ATF_NAMESPACE"

_MINTED: list[str] = []


def current() -> str:
    """This run's token.

    `ATF_NAMESPACE` when it is set, and a token minted once per process otherwise. Every worker of a
    `--jobs` run is handed a different one, so two of them generating the same recognition value is
    not something a suite has to arrange against.
    """
    named = os.environ.get(VARIABLE, "").strip()
    if named:
        return named
    if not _MINTED:
        _MINTED.append(uuid.uuid4().hex[:8])
    return _MINTED[0]


def within(name: str) -> str:
    """`within("guest")` is `guest-3f9a1c04` — a name nothing else in flight will generate.

    What a factory writes when its resource is recognised by a value it makes up.
    """
    return f"{name}-{current()}"


def hand_to(environment: dict[str, str], token: str) -> dict[str, str]:
    """A copy of an environment with the token in it, for a process about to be started."""
    return {**environment, VARIABLE: token}
