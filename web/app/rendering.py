"""One way to render a page, so every page gets the same chrome and the same guards.

A new page calls `render(...)` with a template name and its own context and inherits the
navigation, the signed-in account, the CSRF token and the CSP nonce without knowing any
of them exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from .queries import Account
from .services import Services


@dataclass(frozen=True)
class NavItem:
    endpoint: str
    label: str


# The navigation lives here and nowhere else. Adding a page is: write the route, write
# the template, add one line to this list.
NAV: tuple[NavItem, ...] = (
    NavItem("downloads_page", "Downloads"),
    NavItem("account_page", "Account"),
)


def render(
    request: Request,
    svc: Services,
    template: str,
    context: dict[str, Any] | None = None,
    *,
    account: Account | None = None,
    status_code: int = 200,
) -> Response:
    token, fresh = svc.csrf.token(request)
    here = request.url.path
    nav = [
        {"label": item.label, "href": str(request.url_for(item.endpoint).path),
         "active": str(request.url_for(item.endpoint).path) == here}
        for item in NAV
    ]
    payload: dict[str, Any] = {
        "account": account,
        "nav": nav,
        "csrf_token": token,
        "settings": svc.settings,
        "nonce": getattr(request.state, "csp_nonce", ""),
    }
    payload.update(context or {})

    response = svc.templates.TemplateResponse(request, template, payload, status_code=status_code)
    if fresh:
        svc.csrf.attach(response, token)
    return response
