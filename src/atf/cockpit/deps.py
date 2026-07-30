"""The one session the web app serves, as a FastAPI dependency.

A module-level singleton because a session holds every environment's caches and a per-request one
would re-bootstrap the suite on every page. `set_session` exists so a test can hand it one pointed
at a project of its own.
"""

from __future__ import annotations

from ..engine.session import Session

_session: Session | None = None


def get_session() -> Session:
    global _session
    if _session is None:
        _session = Session()
    return _session


def set_session(session: Session | None) -> None:
    global _session
    _session = session
