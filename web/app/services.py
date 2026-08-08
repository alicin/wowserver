"""The wiring. One object holding everything a route might need, built once at startup.

Routes reach it through `request.app.state.services`, never through module-level
globals, which is what makes the app testable: a test builds a Services with a stub
Database and a temp-directory catalogue and mounts the same routers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from starlette.templating import Jinja2Templates

from . import wowdata
from .catalog import CatalogStore
from .config import Settings
from .db import Database
from .queries import AccountRepo
from .ratelimit import SlidingWindow
from .sessions import CsrfGuard, SessionManager

TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True)
class Services:
    settings: Settings
    db: Database
    accounts: AccountRepo
    catalog: CatalogStore
    sessions: SessionManager
    csrf: CsrfGuard
    login_limiter: SlidingWindow
    templates: Jinja2Templates


def build(settings: Settings) -> Services:
    db = Database(settings)
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    # Formatters as globals rather than filters applied in each route: a template that
    # needs `played()` should not require the handler to have thought of it.
    templates.env.globals.update(
        played=wowdata.played,
        filesize=wowdata.filesize,
        when=wowdata.when,
        age=wowdata.age,
        server_name=settings.server_name,
        realmlist=settings.realmlist,
    )
    templates.env.trim_blocks = True
    templates.env.lstrip_blocks = True

    return Services(
        settings=settings,
        db=db,
        accounts=AccountRepo(db, settings),
        catalog=CatalogStore(settings.manifest_path, settings.download_root),
        sessions=SessionManager(settings),
        csrf=CsrfGuard(settings),
        login_limiter=SlidingWindow(
            settings.login_window,
            {"ip": settings.login_max_per_ip, "user": settings.login_max_per_user},
        ),
        templates=templates,
    )
