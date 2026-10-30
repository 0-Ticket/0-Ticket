"""PostgreSQL Lookup store (box 7, D-002). Tables: migration 0060.

A replace deletes and inserts in one transaction, so a rejected table leaves the
old one in place. IP values are searched with ``network >>= value`` (GiST index);
host names with ``lower(hostname)``. Rows come back through ``validate_contract``.
"""

from collections.abc import Mapping, Sequence

import psycopg
from psycopg.types.json import Jsonb

from soc.config import Settings
from soc.contracts import AssetInfo, validate_contract
from soc.db import connect

from .base import UserRow
from .checks import check_assets, check_users, parse_ip

_ASSET_COLUMNS = (
    "match, hostname, criticality, owner, zone, shared, valid_from, valid_to, extensions"
)
_VALID_AT = (
    "(valid_from IS NULL OR valid_from <= %(at)s) AND (valid_to IS NULL OR %(at)s < valid_to)"
)


class PostgresLookupStore:
    def __init__(self, conn: psycopg.Connection):
        self._conn = conn

    def replace_assets(self, rows: Sequence[AssetInfo]) -> int:
        assets = check_assets(rows)
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute("DELETE FROM lookup_assets")
            cur.executemany(
                f"INSERT INTO lookup_assets (network, {_ASSET_COLUMNS})"
                " VALUES (%s::cidr, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        a.match,
                        a.match,
                        a.hostname,
                        a.criticality,
                        a.owner,
                        a.zone,
                        a.shared,
                        a.valid_from,
                        a.valid_to,
                        Jsonb(a.extensions),
                    )
                    for a in assets
                ],
            )
        return len(assets)

    def replace_users(self, rows: Sequence[UserRow]) -> int:
        users = check_users(rows)
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute("DELETE FROM lookup_users")
            cur.executemany(
                "INSERT INTO lookup_users"
                " (user_name, dept, privileged, valid_from, valid_to, extensions)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                [
                    (
                        r.user.user,
                        r.user.dept,
                        r.user.privileged,
                        r.valid_from,
                        r.valid_to,
                        Jsonb(r.user.extensions),
                    )
                    for r in users
                ],
            )
        return len(users)

    def asset_candidates(self, value: str, at: int) -> list[AssetInfo]:
        address = parse_ip(value)
        if address is None:
            where, params = "lower(hostname) = lower(%(value)s)", {"value": value, "at": at}
        else:
            where, params = "network >>= %(value)s::inet", {"value": str(address), "at": at}
        rows = self._all(
            f"SELECT {_ASSET_COLUMNS} FROM lookup_assets WHERE {where} AND {_VALID_AT} ORDER BY id",
            params,
        )
        names = _ASSET_COLUMNS.split(", ")
        return [validate_contract("AssetInfo", dict(zip(names, row, strict=True))) for row in rows]

    def user_candidates(self, user: str, at: int) -> list[UserRow]:
        rows = self._all(
            "SELECT user_name, dept, privileged, extensions, valid_from, valid_to"
            f" FROM lookup_users WHERE user_name = %(user)s AND {_VALID_AT} ORDER BY id",
            {"user": user, "at": at},
        )
        return [
            UserRow(
                validate_contract(
                    "UserInfo",
                    {"user": name, "dept": dept, "privileged": privileged, "extensions": ext},
                ),
                valid_from,
                valid_to,
            )
            for name, dept, privileged, ext, valid_from, valid_to in rows
        ]

    def close(self) -> None:
        self._conn.close()

    def _all(self, query, params):
        with self._conn.transaction():
            return self._conn.execute(query, params).fetchall()


def create_postgres_lookups(settings: Settings, environ: Mapping[str, str]) -> PostgresLookupStore:
    """The ``postgresql.lookups`` factory: connects with ``[database]`` settings."""
    return PostgresLookupStore(connect(settings, environ))
