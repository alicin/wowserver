"""Sign in and sign out.

The password check is `srp6.verify_password` against the salt and verifier already in
acore_auth — the same values the game's own login uses, so there is no second password
to remember and no second thing to keep in sync.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import srp6
from ..deps import ServicesDep
from ..rendering import render
from ..sessions import SessionData, client_ip, verifier_fingerprint

log = logging.getLogger("portal.auth")

router = APIRouter()

# Deliberately identical for "no such account", "wrong password" and "malformed input".
# Anything more specific tells whoever is guessing which of the five names is real.
BAD_CREDENTIALS = "That account name and password don't match."


def _safe_next(raw: str | None) -> str:
    """Only ever redirect somewhere on this site.

    An open redirect on a login page is the classic phishing primitive: a link that
    really does go to the portal, really does sign you in, and then hands you to
    somebody else's copy of it. A `next` must be a rooted path, not `//evil.example`
    (protocol-relative) and not `/\\evil.example`, both of which browsers treat as
    absolute URLs.
    """
    if not raw or not raw.startswith("/"):
        return "/"
    if raw.startswith("//") or raw.startswith("/\\"):
        return "/"
    return raw


@router.get("/login", name="login_page")
def login_page(request: Request, svc: ServicesDep):
    if svc.sessions.read(request) is not None:
        return RedirectResponse(_safe_next(request.query_params.get("next")), status_code=303)
    return render(
        request,
        svc,
        "login.html",
        {"next": _safe_next(request.query_params.get("next")), "error": None},
    )


@router.post("/login", name="login_submit")
def login_submit(
    request: Request,
    svc: ServicesDep,
    username: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "/",  # noqa: A002 - the form field is named `next`
):
    destination = _safe_next(next)

    def fail(message: str, status_code: int = 400):
        return render(
            request,
            svc,
            "login.html",
            {"next": destination, "error": message},
            status_code=status_code,
        )

    if not svc.csrf.valid(request, csrf_token):
        # Usually a stale tab or a browser that dropped the cookie, not an attack.
        return fail("That form expired. Try again.", status_code=400)

    username = username.strip()
    ip = client_ip(request, svc.settings)
    # Key on the submitted string, uppercased the way the account table stores it, so
    # "ali" and "ALI" share one budget and cannot be used to double it.
    keys = {"ip": ip, "user": srp6.upper_latin(username).decode("utf-8", "replace")}

    decision = svc.login_limiter.check(keys)
    if not decision.allowed:
        minutes = max(decision.retry_after // 60, 1)
        log.warning("login throttled for ip=%s", ip)
        return fail(f"Too many sign-in attempts. Try again in {minutes} min.", status_code=429)

    # 32 is acore_auth.account.username's column width; longer cannot exist, and this
    # bounds the work an attacker can make the SHA1 do.
    if not username or len(username) > 32 or not password or len(password) > 256:
        svc.login_limiter.record(keys)
        return fail(BAD_CREDENTIALS, status_code=401)

    credentials = svc.accounts.credentials(username)
    if credentials is None:
        # Same work, same shape, same timing as a real account with a wrong password —
        # including the log line, which is not free. Measured on the fixture stack the
        # two branches differ by under 0.1 ms out of ~14 ms; leaving the logging on one
        # side only made it 0.7 ms, which is a signal. The username is deliberately not
        # logged here: it is attacker-controlled text and it does not name an account.
        srp6.dummy_verify(username, password)
        svc.login_limiter.record(keys)
        log.info("failed password for an unknown account from ip=%s", ip)
        return fail(BAD_CREDENTIALS, status_code=401)

    if not srp6.verify_password(
        credentials.username, password, credentials.salt, credentials.verifier
    ):
        svc.login_limiter.record(keys)
        log.info("failed password for account id=%d from ip=%s", credentials.account_id, ip)
        return fail(BAD_CREDENTIALS, status_code=401)

    svc.login_limiter.reset(keys)
    log.info("signed in account id=%d from ip=%s", credentials.account_id, ip)

    response = RedirectResponse(destination, status_code=303)
    svc.sessions.issue(
        response,
        SessionData(
            account_id=credentials.account_id,
            username=credentials.username,
            fingerprint=verifier_fingerprint(svc.settings.secret_key, credentials.verifier),
        ),
    )
    return response


@router.post("/logout", name="logout")
def logout(
    request: Request,
    svc: ServicesDep,
    csrf_token: Annotated[str, Form()] = "",
):
    # POST + CSRF even for logout: a forced sign-out is a nuisance attack, and the
    # cost of closing it is one hidden input.
    if not svc.csrf.valid(request, csrf_token):
        return RedirectResponse("/", status_code=303)
    response = RedirectResponse(request.url_for("login_page").path, status_code=303)
    svc.sessions.clear(response)
    return response
