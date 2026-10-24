"""Shared setup for the `db` tests that read a test schema through the read-only account.

A test schema is created by the writable account, so the read-only account the
`readonly_` store factories use has no privileges on it. Without USAGE the
read-only connection does not even see the tables: the schema is skipped while
the name is resolved, so every read fails with `UndefinedTable` (#106).

The writable connection that created the schema owns it, so it is the one that
grants. The read-only account is only granted USAGE and SELECT, which keeps the
tests that assert a write fails failing on the read-only transaction.
"""

import os

from psycopg import sql

from soc.config import load_config
from soc.db import connect_readonly

GRANTS = (
    "GRANT USAGE ON SCHEMA {schema} TO {role}",
    "GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {role}",
)


def readonly_environ() -> dict[str, str]:
    """The environment with a read-only URL, falling back to the writable one.

    CI grants one account, so there is no separate read-only URL there.
    """
    environ = dict(os.environ)
    environ.setdefault("DATABASE_READONLY_URL", environ["DATABASE_URL"])
    return environ


def readonly_role(environ: dict[str, str] | None = None) -> str:
    """The role name the read-only URL logs in as, asked of the server.

    Read from the connection rather than parsed out of the URL, so no password
    is handled here.
    """
    environ = environ or readonly_environ()
    with connect_readonly(load_config(environ=environ), environ) as connection:
        return connection.execute("SELECT current_user").fetchone()[0]


def grant_readonly(prepared, schema: str, environ: dict[str, str] | None = None) -> None:
    """Let the read-only account read `schema`, through the connection that owns it.

    Call it after the migrations: `ON ALL TABLES` only covers the tables that
    exist at grant time.
    """
    role = readonly_role(environ)
    for statement in GRANTS:
        prepared.execute(
            sql.SQL(statement).format(schema=sql.Identifier(schema), role=sql.Identifier(role))
        )
