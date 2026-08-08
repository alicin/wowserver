"""Every SQL statement the portal runs, and the row -> domain object mapping.

Routes never see SQL and never see a raw row; they get dataclasses. That is what makes
"add a page" a small change: a new page needs a new function here and a new template,
not edits scattered through the request handlers.

All statements are parameterised. There is no f-string, no %-format and no .format()
anywhere near a query — the two identifiers that *are* interpolated (the schema names)
come from Settings, never from a request, and are used to pick which connection to open
rather than being pasted into SQL text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .config import Settings
from .db import Database
from . import wowdata


@dataclass(frozen=True)
class Credentials:
    """The three fields a password check needs, and nothing else."""

    account_id: int
    username: str
    salt: bytes
    verifier: bytes


@dataclass(frozen=True)
class Account:
    id: int
    username: str
    expansion: int
    joindate: datetime | None
    last_login: datetime | None
    online: bool
    locked: bool
    gm_level: int
    gm_realm: int | None
    total_seconds: int

    @property
    def expansion_name(self) -> str:
        return wowdata.EXPANSIONS.get(self.expansion, f"Expansion {self.expansion}")

    @property
    def gm_title(self) -> str:
        return wowdata.GM_LEVELS.get(self.gm_level, f"Level {self.gm_level}")

    @property
    def is_gm(self) -> bool:
        return self.gm_level > 0


@dataclass(frozen=True)
class Character:
    guid: int
    name: str
    level: int
    race_id: int
    class_id: int
    gender: int
    money: int
    total_seconds: int
    online: bool

    @property
    def race(self) -> str:
        return wowdata.RACES.get(self.race_id, f"Race {self.race_id}")

    @property
    def klass(self) -> str:
        return wowdata.CLASSES.get(self.class_id, f"Class {self.class_id}")

    @property
    def class_color(self) -> str:
        return wowdata.class_color(self.class_id)

    @property
    def faction(self) -> str:
        return wowdata.faction_of(self.race_id)

    @property
    def gold(self) -> int:
        return self.money // 10000


@dataclass(frozen=True)
class Realm:
    name: str
    address: str
    port: int


class AccountRepo:
    def __init__(self, db: Database, settings: Settings) -> None:
        self._db = db
        self._s = settings

    # -- authentication --------------------------------------------------------

    def credentials(self, username: str) -> Credentials | None:
        """Look up salt+verifier by username.

        The comparison is on `username` alone: acore_auth.account.username has a UNIQUE
        index and a _unicode_ci collation, so MySQL already matches case-insensitively
        the same way the game's own login does. No LOWER()/UPPER() wrapper, which would
        also make the index unusable.
        """
        row = self._db.query_one(
            self._s.db_auth,
            "SELECT id, username, salt, verifier FROM account WHERE username = %s",
            (username,),
        )
        if row is None:
            return None
        return Credentials(
            account_id=int(row["id"]),
            username=str(row["username"]),
            salt=bytes(row["salt"]),
            verifier=bytes(row["verifier"]),
        )

    # -- profile ---------------------------------------------------------------

    def account(self, account_id: int) -> Account | None:
        row = self._db.query_one(
            self._s.db_auth,
            """
            SELECT  a.id, a.username, a.expansion, a.joindate, a.last_login,
                    a.online, a.locked, a.totaltime,
                    aa.gmlevel, aa.RealmID
            FROM account AS a
            LEFT JOIN account_access AS aa ON aa.id = a.id
            WHERE a.id = %s
            ORDER BY aa.gmlevel DESC
            LIMIT 1
            """,
            (account_id,),
        )
        if row is None:
            return None
        # ORDER BY gmlevel DESC + LIMIT 1 picks the strongest grant when an account has
        # per-realm rows as well as the RealmID = -1 "all realms" row. Showing the
        # highest is the honest answer to "am I a GM here".
        return Account(
            id=int(row["id"]),
            username=str(row["username"]),
            expansion=int(row["expansion"]),
            joindate=row["joindate"],
            last_login=row["last_login"],
            online=bool(row["online"]),
            locked=bool(row["locked"]),
            gm_level=int(row["gmlevel"]) if row["gmlevel"] is not None else 0,
            gm_realm=int(row["RealmID"]) if row["RealmID"] is not None else None,
            total_seconds=int(row["totaltime"] or 0),
        )

    def characters(self, account_id: int) -> list[Character]:
        rows = self._db.query(
            self._s.db_characters,
            """
            SELECT guid, name, level, race, class, gender, money, totaltime, online
            FROM characters
            WHERE account = %s AND deleteDate IS NULL
            ORDER BY level DESC, name ASC
            """,
            (account_id,),
        )
        return [
            Character(
                guid=int(r["guid"]),
                name=str(r["name"]),
                level=int(r["level"]),
                race_id=int(r["race"]),
                class_id=int(r["class"]),
                gender=int(r["gender"]),
                money=int(r["money"]),
                total_seconds=int(r["totaltime"] or 0),
                online=bool(r["online"]),
            )
            for r in rows
        ]

    def realm(self) -> Realm | None:
        """The realm row the auth server hands to clients after login.

        Worth surfacing (to GMs) because acore_auth.realmlist.address is the classic
        private-server failure: log in fine, then hang at "Entering world" forever
        because the auth server told the client to connect somewhere unreachable.
        docs/hosting.md 5.2.
        """
        row = self._db.query_one(
            self._s.db_auth,
            "SELECT name, address, port FROM realmlist ORDER BY id LIMIT 1",
        )
        if row is None:
            return None
        return Realm(
            name=str(row["name"]),
            address=str(row["address"]),
            port=int(row["port"]),
        )
