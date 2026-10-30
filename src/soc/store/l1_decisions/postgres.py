"""PostgreSQL L1 decision store (boxes 15, 20, L1 result read, C23, D-002). Table: migration 0091.

Every call runs in its own transaction. Rows hold the whole C23 as jsonb and
are turned back into the contract model through ``validate_contract``.
"""

from collections.abc import Mapping

import psycopg
from psycopg import errors, sql
from psycopg.types.json import Jsonb

from soc.config import Settings
from soc.contracts import L1DecisionRecord, validate_contract
from soc.db import connect, connect_readonly
from soc.store.paging import DEFAULT_PAGE_LIMIT, encode_cursor

from .base import DecisionPage, DuplicateDecisionError
from .checks import check_decision, check_list_args, check_subject_type, decode_decision_cursor


class PostgresL1DecisionStore:
    def __init__(self, conn: psycopg.Connection, *, owns_connection: bool = False):
        self._conn = conn
        self._owns_connection = owns_connection

    def save(self, record: L1DecisionRecord) -> L1DecisionRecord:
        record = check_decision(record)
        try:
            with self._conn.transaction():
                self._conn.execute(
                    "INSERT INTO l1_decisions (decision_id, subject_type, subject_id, decision,"
                    " reason, created_at, record) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        record.decision_id,
                        record.subject_type,
                        record.subject_id,
                        record.decision,
                        record.reason,
                        record.created_at,
                        Jsonb(record.model_dump(mode="json")),
                    ),
                )
        except errors.UniqueViolation:
            raise DuplicateDecisionError("this decision_id is already stored") from None
        return record

    def get(self, subject_type: str, subject_id: str) -> L1DecisionRecord | None:
        check_subject_type(subject_type)
        with self._conn.transaction():
            row = self._conn.execute(
                "SELECT record FROM l1_decisions WHERE subject_type = %s AND subject_id = %s"
                " ORDER BY created_at DESC, seq DESC LIMIT 1",
                (subject_type, subject_id),
            ).fetchone()
        return validate_contract("L1DecisionRecord", row[0]) if row else None

    def list(
        self,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
        decision: str | None = None,
        reason: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> DecisionPage:
        check_list_args(subject_type, decision, reason, limit, subject_id)
        after = decode_decision_cursor(cursor)
        conditions, params = [], []
        for column, value in (
            ("subject_type", subject_type),
            ("subject_id", subject_id),
            ("decision", decision),
            ("reason", reason),
        ):
            if value is not None:
                conditions.append(sql.SQL("{} = %s").format(sql.Identifier(column)))
                params.append(value)
        if after is not None:
            conditions.append(sql.SQL("(created_at, seq) < (%s, %s)"))
            params.extend(after)
        where = (
            sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions) if conditions else sql.SQL("")
        )
        query = sql.SQL(
            "SELECT seq, record FROM l1_decisions{} ORDER BY created_at DESC, seq DESC LIMIT %s"
        ).format(where)
        with self._conn.transaction():
            rows = self._conn.execute(query, [*params, limit + 1]).fetchall()
        page = rows[:limit]
        items = tuple(validate_contract("L1DecisionRecord", rec) for _, rec in page)
        next_cursor = None
        if len(rows) > limit:
            next_cursor = encode_cursor([items[-1].created_at, page[-1][0]])
        return DecisionPage(items, next_cursor)

    def close(self) -> None:
        # A connection the caller handed over goes back to its pool, not here (#104).
        if self._owns_connection:
            self._conn.close()


def create_postgres_l1_decisions(
    settings: Settings,
    environ: Mapping[str, str],
    connection: psycopg.Connection | None = None,
) -> PostgresL1DecisionStore:
    """The ``postgresql.l1_decisions`` factory: connects with ``[database]`` settings.

    With ``connection`` the store reads through a connection the caller borrowed
    from a pool: it is used as it is and never closed here (#104).
    """
    return PostgresL1DecisionStore(
        connection or connect(settings, environ), owns_connection=connection is None
    )


def create_postgres_readonly_l1_decisions(
    settings: Settings,
    environ: Mapping[str, str],
    connection: psycopg.Connection | None = None,
) -> PostgresL1DecisionStore:
    """The ``postgresql.readonly_l1_decisions`` factory: reads work, every save fails.

    With ``connection`` the store reads through a connection the caller borrowed
    from a pool: it is used as it is and never closed here (#104).
    """
    return PostgresL1DecisionStore(
        connection or connect_readonly(settings, environ), owns_connection=connection is None
    )
