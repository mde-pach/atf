"""The cockpit FastAPI app. Single-user, localhost by default, no built-in auth."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from .deps import Cockpit, set_cockpit
from .routers import activity, authoring, catalog, compose, overview, scenarios, search
from .view import STATIC_DIR, templates


def create_app(env: str | None = None, cockpit: Cockpit | None = None) -> FastAPI:
    app = FastAPI(title="ATF Cockpit", version=__version__, docs_url=None, redoc_url=None)
    set_cockpit(cockpit or Cockpit(env))

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
