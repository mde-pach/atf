"""The cockpit FastAPI app. Single-user, localhost by default, no built-in auth."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..session import Session
from .deps import get_session, set_session
from .routers import activity, authoring, catalog, compose, overview, scenarios, search
from .view import STATIC_DIR, templates


def create_app(
    env: str | None = None, session: Session | None = None, mcp_host: str | None = None
) -> FastAPI:
    """The cockpit, and — when a host is given for it — the MCP endpoint beside it.

    One server for both views of one suite: the pages a person reads, and the same vocabulary
    offered to an agent. `mcp_host` is the host and not a flag, the endpoint having to
    know which host it is reachable at; `None` means nobody asked, and nothing about MCP is even
    imported.
    """
    app = FastAPI(title="ATF Cockpit", version=__version__, docs_url=None, redoc_url=None)
    set_session(session or Session(env))

    if mcp_host is not None:
        from ..agent.mcp import MOUNT, endpoint

        served, lifespan = endpoint(get_session(), mcp_host)
        # Assigned, not passed to `FastAPI(...)`: the endpoint needs the session, which is only
        # settled above, and Starlette reads this when the server starts.
        app.router.lifespan_context = lifespan
        app.mount(MOUNT, served)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    for router in (
        overview.router,
        scenarios.router,
        catalog.router,
        activity.router,
        authoring.router,
        compose.router,
        search.router,
    ):
        app.include_router(router)

    @app.exception_handler(HTTPException)
    def _http_error(request: Request, exc: HTTPException) -> HTMLResponse:
        """Errors arrive beside the page, never as a swap that destroys what you were reading."""
        response = templates.TemplateResponse(
            request,
            "partials/error.html",
            {"request": request, "status": exc.status_code, "detail": exc.detail},
            status_code=exc.status_code,
        )
        response.headers["HX-Reswap"] = "none"
        return response

    return app
