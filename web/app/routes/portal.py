"""The two signed-in pages: the download list and the account page.

Both take `RequiredAccount`, so neither has to think about authentication — an
unauthenticated request never reaches the function body.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, RedirectResponse

from ..deps import RequiredAccount, ServicesDep
from ..rendering import render

router = APIRouter()


@router.get("/", name="home", include_in_schema=False)
def home(request: Request):
    return RedirectResponse(request.url_for("downloads_page").path, status_code=303)


@router.get("/downloads", name="downloads_page")
def downloads_page(request: Request, svc: ServicesDep, account: RequiredAccount):
    return render(
        request,
        svc,
        "downloads.html",
        {"catalog": svc.catalog.load()},
        account=account,
    )


@router.get("/account", name="account_page")
def account_page(request: Request, svc: ServicesDep, account: RequiredAccount):
    # The realm row is only shown to GMs: to a friend it is noise, but to whoever runs
    # the server a wrong `address` here is the difference between "logs in fine" and
    # "hangs at Entering World", and it is the first thing to check.
    realm = svc.accounts.realm() if account.is_gm else None
    return render(
        request,
        svc,
        "account.html",
        {"characters": svc.accounts.characters(account.id), "realm": realm},
        account=account,
    )


@router.get("/healthz", name="healthz", include_in_schema=False)
def healthz():
    """Liveness: is the process answering? No database, no manifest, no auth.

    Deliberately separate from /readyz. If the healthcheck touched MySQL, then MySQL
    being briefly down would make Docker kill and restart a perfectly healthy portal.
    """
    return PlainTextResponse("ok")


@router.get("/readyz", name="readyz", include_in_schema=False)
def readyz(svc: ServicesDep):
    """Readiness: can we actually serve? Used by a human or a deploy script, not by
    the container healthcheck."""
    catalog = svc.catalog.load()
    db_ok = svc.db.healthy()
    lines = [
        f"database: {'ok' if db_ok else 'FAIL'}",
        f"artefacts: {len(catalog.artifacts)}",
        f"manifest: {catalog.error or 'ok'}",
    ]
    return PlainTextResponse("\n".join(lines) + "\n", status_code=200 if db_ok else 503)
