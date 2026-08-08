"""App factory: build the services, mount the routers, install the middleware.

Adding a page is a new module under routes/ with a `router`, one entry in ROUTERS, and
one entry in rendering.NAV if it belongs in the navigation. Nothing else in this file
should need to change.
"""

from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import pymysql
from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import RedirectResponse, Response

from . import services
from .config import load_settings
from .deps import NeedsLogin, current_account
from .rendering import render
from .routes import auth, downloads, portal

log = logging.getLogger("portal")

ROUTERS = (auth.router, portal.router, downloads.router)


def create_app() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    settings = load_settings()

    app = FastAPI(
        title=f"{settings.server_name} portal",
        # No interactive docs. They would enumerate every route to anybody who asks,
        # and there is no API here worth documenting to a browser.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.services = services.build(settings)
    for router in ROUTERS:
        app.include_router(router)

    _install_middleware(app, settings)
    _install_error_handlers(app)
    return app


def _install_middleware(app: FastAPI, settings) -> None:
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        # A per-response nonce is what lets the page keep its stylesheet and its one
        # small script inline (no CDN, no extra requests) without opening the door to
        # 'unsafe-inline'. rendering.render() passes it into the template.
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response: Response = await call_next(request)

        csp = (
            "default-src 'none'; "
            f"style-src 'nonce-{nonce}'; "
            f"script-src 'nonce-{nonce}'; "
            "img-src 'self' data:; "
            "form-action 'self'; "
            "base-uri 'none'; "
            "frame-ancestors 'none'"
        )
        response.headers.setdefault("content-security-policy", csp)
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("referrer-policy", "no-referrer")
        response.headers.setdefault("x-frame-options", "DENY")
        # The portal needs none of these; deny them rather than inherit a default.
        response.headers.setdefault(
            "permissions-policy", "geolocation=(), camera=(), microphone=(), interest-cohort=()"
        )
        if settings.tls:
            # Only under TLS. Sending HSTS over plain HTTP is ignored by browsers, and
            # sending it from a host that later loses its certificate locks people out.
            response.headers.setdefault(
                "strict-transport-security", "max-age=31536000; includeSubDomains"
            )
        return response


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NeedsLogin)
    async def needs_login(request: Request, exc: NeedsLogin):
        # A PATH, not request.url_for()'s absolute URL. Building an absolute redirect
        # means trusting the Host header the proxy forwarded, and any proxy that sends
        # nginx's $host rather than $http_host drops the port — so a portal reached on
        # :8080 redirects the browser to :80 and login appears to be down. A relative
        # Location is unambiguous and is what RFC 7231 has allowed since 2014.
        target = request.url_for("login_page").path
        return RedirectResponse(
            f"{target}?{urlencode({'next': exc.next_url})}", status_code=303
        )

    @app.exception_handler(pymysql.MySQLError)
    async def database_down(request: Request, exc: pymysql.MySQLError):
        """A 503 that says something true, instead of a bare 500.

        This is the expected state for the first ninety minutes of a fresh deploy:
        worldserver owns the creation of acore_auth (deploy/docker-compose.yml), the
        portal's GRANT cannot be run until that schema exists, and the portal may well
        be up before either. It is also what a friend sees if MySQL is restarting.
        The exception text is not shown — it can carry the connection string.
        """
        log.error("database error serving %s", request.url.path, exc_info=exc)
        return _error_response(
            request,
            503,
            "The server is still starting up, or the database is briefly away. "
            "Give it a minute and reload.",
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return _error_response(request, exc.status_code, str(exc.detail))


def _error_response(request: Request, status_code: int, detail: str) -> Response:
    svc = request.app.state.services
    # Downloads are fetched by curl and by download managers at least as often as by a
    # browser, so only send the HTML error page to something that asked for HTML.
    if "text/html" not in request.headers.get("accept", ""):
        return Response(
            f"{status_code} {detail}\n", status_code=status_code, media_type="text/plain"
        )

    account = None
    try:
        account = current_account(request, svc)
    except Exception:  # noqa: BLE001 - the error page must not raise a second error
        # Most likely the database error we are already reporting. Render signed out.
        account = None

    return render(
        request,
        svc,
        "error.html",
        {"status": status_code, "detail": detail},
        account=account,
        status_code=status_code,
    )


app = create_app()
