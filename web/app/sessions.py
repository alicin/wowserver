"""Signed session cookie, CSRF token, and working out who the caller actually is.

The session is a signed cookie rather than server-side state because there is no store
to keep it in: the portal's MySQL user is read-only by design, and adding a writable
store to hold three friends' logins would be the largest moving part in the app.
"""

from __future__ import annotations

import ipaddress
import logging
import secrets
from dataclasses import dataclass

import hmac
from hashlib import sha256

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.requests import Request
from starlette.responses import Response

from .config import Settings

log = logging.getLogger("portal.session")

SESSION_COOKIE = "wow_session"
CSRF_COOKIE = "wow_csrf"
CSRF_FIELD = "csrf_token"


@dataclass(frozen=True)
class SessionData:
    account_id: int
    username: str
    fingerprint: str
    """HMAC of the account's verifier, truncated. See `verifier_fingerprint`."""


def verifier_fingerprint(secret_key: str, verifier: bytes) -> str:
    """A tag that changes when the account's password changes.

    Stored in the cookie and re-checked on every request, so `.account set password`
    (or a friend changing their own password later) invalidates sessions that were
    minted under the old one. It is an HMAC and not a plain hash of the verifier so the
    cookie carries no offline-crackable material: without the app secret the tag says
    nothing about the verifier it came from.
    """
    return hmac.new(secret_key.encode(), verifier, sha256).hexdigest()[:16]


class SessionManager:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        # A salt distinct from the CSRF serializer's, so a token minted for one purpose
        # cannot be replayed as the other even though both use the same secret.
        self._serializer = URLSafeTimedSerializer(settings.secret_key, salt="wow-portal-session")

    # -- read ------------------------------------------------------------------

    def read(self, request: Request) -> SessionData | None:
        raw = request.cookies.get(SESSION_COOKIE)
        if not raw:
            return None
        try:
            payload = self._serializer.loads(raw, max_age=self._s.session_max_age)
        except SignatureExpired:
            return None
        except BadSignature:
            # Either a tampered cookie or a rotated PORTAL_SECRET_KEY. Both mean
            # "logged out"; neither is worth an error page.
            log.info("rejected a session cookie with a bad signature")
            return None
        try:
            return SessionData(
                account_id=int(payload["id"]),
                username=str(payload["u"]),
                fingerprint=str(payload["v"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    # -- write -----------------------------------------------------------------

    def issue(self, response: Response, data: SessionData) -> None:
        token = self._serializer.dumps(
            {"id": data.account_id, "u": data.username, "v": data.fingerprint}
        )
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=self._s.session_max_age,
            httponly=True,
            samesite="lax",
            # Only when TLS is actually terminating in front of us. Setting Secure on a
            # plain-HTTP deployment does not harden anything, it just makes the cookie
            # silently never come back and login appear to do nothing.
            secure=self._s.cookie_secure,
            path="/",
        )

    def clear(self, response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax",
                               secure=self._s.cookie_secure)


class CsrfGuard:
    """Double-submit token: same random value in an HttpOnly cookie and a form field.

    SameSite=Lax already stops a cross-site POST from carrying the session cookie, so
    this is defence in depth — but it is also what protects the *login* form, which by
    definition has no session yet. Forced-login CSRF (an attacker silently signing a
    friend into the attacker's account) is the real thing being closed here.
    """

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def token(self, request: Request) -> tuple[str, bool]:
        """-> (token, needs_setting). Split from `attach` because the template needs the
        token before there is a response object to put the cookie on."""
        existing = request.cookies.get(CSRF_COOKIE)
        if existing and len(existing) == 43:  # token_urlsafe(32) is always 43 chars
            return existing, False
        return secrets.token_urlsafe(32), True

    def attach(self, response: Response, token: str) -> None:
        response.set_cookie(
            CSRF_COOKIE,
            token,
            max_age=self._s.session_max_age,
            httponly=True,
            samesite="lax",
            secure=self._s.cookie_secure,
            path="/",
        )

    def valid(self, request: Request, submitted: str | None) -> bool:
        cookie = request.cookies.get(CSRF_COOKIE)
        if not cookie or not submitted:
            return False
        return hmac.compare_digest(cookie, submitted)


def client_ip(request: Request, settings: Settings) -> str:
    """The caller's address, trusting X-Forwarded-For only from a known proxy.

    Behind the front proxy every request has the same peer address (the nginx
    container), so rate limiting on the peer would punish all friends for one
    attacker's guesses. The rightmost XFF entry is the one the trusted proxy appended
    itself and is the only one a client cannot forge; entries to its left are attacker
    controlled and deliberately ignored.
    """
    peer = request.client.host if request.client else "unknown"
    if not _trusted(peer, settings):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    if not forwarded:
        return peer
    candidate = forwarded.split(",")[-1].strip()
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return peer
    return candidate


def _trusted(host: str, settings: Settings) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in settings.trusted_proxies)
