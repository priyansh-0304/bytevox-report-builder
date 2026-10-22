"""App wiring: settings, security headers, routers, and the static frontend."""
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import routes_auth, routes_datasets, routes_reports, routes_share
from .config import Settings
from .db import init_db
from .ratelimit import SlidingWindow

STATIC = Path(__file__).parent / "static"

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    init_db(settings.db_path)

    app = FastAPI(title="Show-your-work report builder", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.login_fails = {}
    app.state.share_limiter = SlidingWindow(limit=120, seconds=60)       # any request to a share link
    app.state.share_fail_limiter = SlidingWindow(limit=20, seconds=300)  # links that did not work

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Defence in depth on top of SameSite=Lax cookies: refuse state-changing requests whose
        # Origin header names a different site.
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "Cross-origin request blocked."}, status_code=403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Robots-Tag"] = "noindex"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        # One readable sentence instead of pydantic's raw error list.
        parts = []
        for err in exc.errors()[:3]:
            where = ".".join(str(p) for p in err["loc"] if p not in ("body", "query", "path"))
            msg = err["msg"].removeprefix("Value error, ")
            parts.append(f"{where}: {msg}" if where else msg)
        return JSONResponse({"detail": "; ".join(parts) or "Invalid request."}, status_code=422)

    app.include_router(routes_auth.router)
    app.include_router(routes_datasets.router)
    app.include_router(routes_reports.router)
    app.include_router(routes_share.router)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    # The single-page app. /s/<token> is the public share page; the token is read by the browser
    # from the URL and sent to /api/shared/<token>.
    @app.get("/", include_in_schema=False)
    @app.get("/s/{token}", include_in_schema=False)
    def index(token: str = ""):
        return FileResponse(STATIC / "index.html")

    return app

