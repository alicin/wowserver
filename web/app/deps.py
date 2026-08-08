"""Request-scoped helpers shared by every route module.

`require_account` is the only thing a new authenticated page needs to depend on. It
resolves the cookie to a live account row, so a page never has to think about sessions,
password rotation or the redirect-to-login dance.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from .queries import Account
from .services import Services
from .sessions import verifier_fingerprint


def services(request: Request) -> Services:
    return request.app.state.services


ServicesDep = Annotated[Services, Depends(services)]


class NeedsLogin(HTTPException):
    """Raised instead of returning a redirect, so it works from any dependency depth.

    main.py turns it into a 303 to /login with a `next` parameter. Carrying the intended
    destination matters here: the link a friend is most likely to be sent is a deep link
    to a download, and bouncing them to the front page after signing in would lose it.
    """

    def __init__(self, request: Request) -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED)
        self.next_url = request.url.path
        if request.url.query:
            self.next_url = f"{self.next_url}?{request.url.query}"


def current_account(request: Request, svc: ServicesDep) -> Account | None:
    session = svc.sessions.read(request)
    if session is None:
        return None

    credentials = svc.accounts.credentials(session.username)
    if credentials is None or credentials.account_id != session.account_id:
        # The account was renamed or deleted while the cookie was alive.
        return None

    expected = verifier_fingerprint(svc.settings.secret_key, credentials.verifier)
    if expected != session.fingerprint:
        # The password changed. Old sessions stop working, which is the behaviour
        # somebody who has just changed a leaked password expects.
        return None

    return svc.accounts.account(session.account_id)


OptionalAccount = Annotated["Account | None", Depends(current_account)]


def require_account(
    request: Request,
    account: OptionalAccount,
) -> Account:
    if account is None:
        raise NeedsLogin(request)
    return account


RequiredAccount = Annotated[Account, Depends(require_account)]
