"""The one session the web app serves, as a FastAPI dependency."""

from __future__ import annotations

from ..session import Session

_session: Session | None = None


def get_session() -> Session:
    global _session
    if _session is None:
        _session = Session()
    return _session


def set_session(session: Session | None) -> None:
    global _session
    _session = session
