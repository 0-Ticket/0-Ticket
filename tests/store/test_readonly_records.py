"""Read-only Alert/Event store for agent tools (boxes 15, 6, 7, docs/security-policy.md 4).

The agent tools read through ``readonly_records``, which connects with the
read-only account ``database.readonly_url_env`` names and forces read-only
transactions, so a write fails even if that account was granted more than SELECT.
"""

import os

import psycopg
import pytest

from soc.config import MissingSecretError, load_config
from soc.db import connect_readonly
from soc.store import open_store
from soc.store.records.base import READONLY_STORE_KIND


def test_readonly_store_refuses_to_use_the_writable_url():
    settings = load_config(environ={})
    with pytest.raises(MissingSecretError, match="DATABASE_READONLY_URL"):
        open_store(
            READONLY_STORE_KIND, settings, environ={"DATABASE_URL": "postgresql://localhost/zt"}
        )


@pytest.mark.db
def test_readonly_connection_reads_but_cannot_write():
    # CI grants one account; the connection-level guard is what fails the write
    # there, and the read-only account is the second layer in a deployment.
    environ = dict(os.environ)
    environ.setdefault("DATABASE_READONLY_URL", environ["DATABASE_URL"])
    with connect_readonly(load_config(environ=environ), environ) as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("CREATE TABLE zt_readonly_probe (probe int)")
