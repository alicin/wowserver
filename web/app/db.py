"""MySQL access for the portal. One connection per request, read-only by grant.

WHY NO CONNECTION POOL
----------------------
The audience is a handful of friends, and a TCP connect plus MySQL handshake to a
container on the same Compose network costs single-digit milliseconds — less than the
SRP6 modexp a login already pays. A pool, by contrast, is a permanent source of
stale-connection bugs (server restarts, wait_timeout, MySQL going away mid-query) that
would need ping-and-retry logic to solve a problem this deployment does not have.

The seam is here on purpose. Everything above this module goes through `connection()`,
so growing into a pool later is a change to this one file. That is also why queries live
in queries.py rather than being inlined into routes.

WHY THE APP CANNOT WRITE
------------------------
Not by convention — by grant. The portal authenticates as a user that holds SELECT on
acore_auth and acore_characters and nothing else (web/sql/grant-webapp.sql). An
injection or a mistake in this codebase therefore cannot change a password, promote an
account or delete a character; the worst it can do is read rows the portal already
shows. `autocommit=True` below is not a transaction policy, it just stops PyMySQL from
opening a transaction it will never commit.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from .config import Settings

log = logging.getLogger("portal.db")


class Database:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    @contextmanager
    def connection(self, database: str) -> Iterator[pymysql.connections.Connection]:
        conn = pymysql.connect(
            host=self._s.db_host,
            port=self._s.db_port,
            user=self._s.db_user,
            password=self._s.db_password,
            database=database,
            charset="utf8mb4",
            autocommit=True,
            cursorclass=DictCursor,
            connect_timeout=self._s.db_connect_timeout,
            read_timeout=self._s.db_read_timeout,
            write_timeout=self._s.db_read_timeout,
            # BINARY(32) columns must come back as bytes, never as a str that a
            # decode would mangle. utf8mb4 + binary_prefix keeps salt and verifier
            # intact; without it PyMySQL would try to decode 32 random bytes.
            binary_prefix=True,
        )
        try:
            yield conn
        finally:
            conn.close()

    def query(self, database: str, sql: str, args: tuple[Any, ...] = ()) -> list[dict]:
        """Run one parameterised SELECT. `args` is the ONLY way values enter a query."""
        with self.connection(database) as conn, conn.cursor() as cur:
            cur.execute(sql, args)
            return list(cur.fetchall())

    def query_one(self, database: str, sql: str, args: tuple[Any, ...] = ()) -> dict | None:
        rows = self.query(database, sql, args)
        return rows[0] if rows else None

    def healthy(self) -> bool:
        """Cheap readiness probe: can we authenticate and read at all?"""
        try:
            self.query(self._s.db_auth, "SELECT 1 AS ok")
            return True
        except Exception:  # noqa: BLE001 - a probe reports false, it does not raise
            log.warning("database readiness probe failed", exc_info=True)
            return False
