"""PostgreSQL branch store (box 25, C21, D-002). Table: migration 0090.

Every call runs in its own transaction. Rows hold the whole C21 as jsonb and
are turned back into the contract model through ``validate_contract``.
"""

from collections.abc import Mapping

import psycopg
from psycopg import errors
from psycopg.types.json import Jsonb

from soc.config import Settings
from soc.contracts import BranchResult, validate_contract
from soc.db import connect, connect_readonly

from .base import DuplicateBranchError, StoredBranch
from .checks import check_branch, check_limit, check_path, check_subject_type


class PostgresBranchStore:
    def __init__(self, conn: psycopg.Connection):
        self._conn = conn

    def save(self, record: BranchResult) -> StoredBranch:
        record = check_branch(record)
        try:
            with self._conn.transaction():
                seq = self._conn.execute(
                    "INSERT INTO branch_results"
                    " (branch_id, subject_type, subject_id, path, created_at, record)"
                    " VALUES (%s, %s, %s, %s, %s, %s) RETURNING seq",
                    (
                        record.branch_id,
                        record.subject_type,
                        record.subject_id,
                        record.path,
                        record.created_at,
                        Jsonb(record.model_dump(mode="json")),
                    ),
                ).fetchone()[0]
        except errors.UniqueViolation:
            raise DuplicateBranchError("this subject or branch_id already has a C21") from None
        return StoredBranch(seq, record)

    def get(self, subject_type: str, subject_id: str) -> BranchResult | None:
        check_subject_type(subject_type)
        with self._conn.transaction():
            row = self._conn.execute(
                "SELECT record FROM branch_results WHERE subject_type = %s AND subject_id = %s",
                (subject_type, subject_id),
            ).fetchone()
        return validate_contract("BranchResult", row[0]) if row else None

    def list_by_path(
        self, path: str, after_seq: int | None, limit: int
    ) -> tuple[StoredBranch, ...]:
        check_path(path)
        check_limit(limit)
        with self._conn.transaction():
            rows = self._conn.execute(
                "SELECT seq, record FROM branch_results"
                " WHERE path = %s AND seq > %s ORDER BY seq LIMIT %s",
                (path, after_seq or 0, limit),
            ).fetchall()
        return tuple(StoredBranch(seq, validate_contract("BranchResult", rec)) for seq, rec in rows)

    def close(self) -> None:
        self._conn.close()


def create_postgres_branches(settings: Settings, environ: Mapping[str, str]) -> PostgresBranchStore:
    """The ``postgresql.branches`` factory: connects with ``[database]`` settings."""
    return PostgresBranchStore(connect(settings, environ))


def create_postgres_readonly_branches(
    settings: Settings, environ: Mapping[str, str]
) -> PostgresBranchStore:
    """The ``postgresql.readonly_branches`` factory: reads work, every save fails."""
    return PostgresBranchStore(connect_readonly(settings, environ))
