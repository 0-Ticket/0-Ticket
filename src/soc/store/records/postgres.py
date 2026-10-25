"""PostgreSQL Alert/Event store (boxes 4, 6, 7, 25, D-002). Migrations 0010, 0011, 0050, 0093, 0094.

Every call runs in its own transaction, so a failed batch leaves neither rows
nor a moved cursor. Rows hold C2, C5 and C13 as json and are turned back into
contract models through ``validate_contract`` on the way out.
"""

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Literal

import psycopg
from psycopg import errors, sql
from psycopg.types.json import Json

from soc.config import Settings
from soc.contracts import AlertRecord, EventRecord, NormalizeFailure, SiemAlert, validate_contract
from soc.db import connect, connect_readonly

from .base import (
    DuplicateRecordError,
    EntityField,
    PurgeResult,
    SaveResult,
    SourceFailure,
    SourceKind,
    StoredAlert,
    StoredSource,
    UnknownRecordError,
    UnknownSourceError,
)
from .checks import (
    check_alert_record,
    check_entity_field,
    check_event_record,
    check_limit,
    check_merge,
    check_normalize_batch,
    check_position,
    check_source_records,
    check_window,
    lookup_value,
    merged_alert,
    retention_cutoff,
)


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


# Per normalized kind: table, ID column, contract name.
_TABLES = {
    "alert": ("alert_records", "alert_id", "AlertRecord"),
    "event": ("event_records", "event_id", "EventRecord"),
}


class PostgresRecordStore:
    def __init__(
        self,
        conn: psycopg.Connection,
        retention_days: int,
        clock: Callable[[], int] = _now_ms,
        *,
        owns_connection: bool = False,
    ):
        self._conn = conn
        self._retention_days = retention_days
        self._clock = clock
        self._owns_connection = owns_connection

    # Source records

    def save_source_records(
        self, items: Sequence[SiemAlert], cursor_key: str, next_cursor: str | None
    ) -> SaveResult:
        items = check_source_records(items)
        now = self._clock()
        inserted = 0
        with self._conn.transaction():
            for item in items:
                cur = self._conn.execute(
                    "INSERT INTO source_records (source_record_id, kind, content, ingested_at)"
                    " VALUES (%s, %s, %s, %s) ON CONFLICT (source_record_id) DO NOTHING",
                    (item.source_record_id, item.kind, Json(item.model_dump(mode="json")), now),
                )
                inserted += cur.rowcount
            self._conn.execute(
                "INSERT INTO ingest_cursors (cursor_key, cursor, updated_at) VALUES (%s, %s, %s)"
                " ON CONFLICT (cursor_key)"
                " DO UPDATE SET cursor = EXCLUDED.cursor, updated_at = EXCLUDED.updated_at",
                (cursor_key, next_cursor, now),
            )
        return SaveResult(inserted, len(items) - inserted)

    def load_cursor(self, cursor_key: str) -> str | None:
        row = self._one("SELECT cursor FROM ingest_cursors WHERE cursor_key = %s", (cursor_key,))
        return row[0] if row else None

    def get_source_record(self, source_record_id: str) -> SiemAlert | None:
        row = self._one(
            "SELECT content FROM source_records WHERE source_record_id = %s", (source_record_id,)
        )
        return validate_contract("SiemAlert", row[0]) if row else None

    def list_source_records(
        self, kind: Literal["alert", "event"], after_seq: int | None, limit: int
    ) -> tuple[StoredSource, ...]:
        check_limit(limit)
        rows = self._all(
            "SELECT seq, ingested_at, content FROM source_records"
            " WHERE kind = %s AND seq > %s ORDER BY seq LIMIT %s",
            (kind, after_seq or 0, limit),
        )
        return tuple(
            StoredSource(seq, ingested_at, validate_contract("SiemAlert", content))
            for seq, ingested_at, content in rows
        )

    # Normalized results

    def save_alert_record(self, record: AlertRecord) -> None:
        record = check_alert_record(record)
        self._save("alert", record.alert_id, record)

    def save_event_record(self, record: EventRecord) -> None:
        record = check_event_record(record)
        self._save("event", record.event_id, record)

    def _save(self, kind: str, record_id: str, record: AlertRecord | EventRecord) -> None:
        try:
            with self._conn.transaction():
                self._insert(kind, record_id, record)
        except errors.ForeignKeyViolation:
            raise UnknownSourceError(f"no {kind} source record for {record_id}") from None
        except errors.UniqueViolation:
            raise DuplicateRecordError(f"{record_id} is already stored") from None

    def _insert(self, kind: str, record_id: str, record: AlertRecord | EventRecord) -> None:
        table, id_column, _ = _TABLES[kind]
        query = sql.SQL(
            "INSERT INTO {} ({}, source_record_id, time, src_ip, dst_ip, host, record)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)"
        ).format(sql.Identifier(table), sql.Identifier(id_column))
        values = (
            record_id,
            record.source_record_id,
            record.time,
            lookup_value(record.src_ip),
            lookup_value(record.dst_ip),
            lookup_value(record.host),
            Json(record.model_dump(mode="json")),
        )
        self._conn.execute(query, values)

    def get_alert_record(self, alert_id: str) -> AlertRecord | None:
        return self._get("alert", alert_id)

    def get_event_record(self, event_id: str) -> EventRecord | None:
        return self._get("event", event_id)

    def _get(self, kind: str, record_id: str):
        table, id_column, contract = _TABLES[kind]
        query = sql.SQL("SELECT record FROM {} WHERE {} = %s").format(
            sql.Identifier(table), sql.Identifier(id_column)
        )
        row = self._one(query, (record_id,))
        return validate_contract(contract, row[0]) if row else None

    def find_alert_records(
        self, field: EntityField, value: str, time_from: int, time_to: int, limit: int
    ) -> tuple[AlertRecord, ...]:
        return self._find("alert", field, value, time_from, time_to, limit)

    def find_event_records(
        self, field: EntityField, value: str, time_from: int, time_to: int, limit: int
    ) -> tuple[EventRecord, ...]:
        return self._find("event", field, value, time_from, time_to, limit)

    def _find(self, kind, field, value, time_from, time_to, limit):
        check_entity_field(field)
        check_limit(limit)
        table, id_column, contract = _TABLES[kind]
        query = sql.SQL(
            "SELECT record FROM {table} WHERE {field} = %s AND time >= %s AND time < %s"
            " ORDER BY time, {id} LIMIT %s"
        ).format(
            table=sql.Identifier(table), field=sql.Identifier(field), id=sql.Identifier(id_column)
        )
        rows = self._all(query, (lookup_value(value), time_from, time_to, limit))
        return tuple(validate_contract(contract, row[0]) for row in rows)

    # Normalization batches (box 4)

    def load_normalize_position(self, kind: SourceKind) -> int | None:
        row = self._one("SELECT last_seq FROM normalize_positions WHERE kind = %s", (kind,))
        return row[0] if row else None

    def save_normalize_batch(
        self,
        kind: SourceKind,
        records: Sequence[AlertRecord] | Sequence[EventRecord],
        failures: Sequence[SourceFailure],
        last_seq: int,
    ) -> None:
        records, failures = check_normalize_batch(kind, records, failures)
        table, id_column, _ = _TABLES[kind]
        now = self._clock()
        try:
            with self._conn.transaction():
                row = self._conn.execute(
                    "SELECT last_seq FROM normalize_positions WHERE kind = %s FOR UPDATE", (kind,)
                ).fetchone()
                check_position(row[0] if row else None, last_seq)
                self._reject_other_outcomes(table, records, failures)
                for record in records:
                    self._insert(kind, getattr(record, id_column), record)
                for item in failures:
                    self._conn.execute(
                        "INSERT INTO normalize_failures"
                        " (source_record_id, source_kind, reason, failed_at, record)"
                        " VALUES (%s, %s, %s, %s, %s)",
                        (
                            item.source_record_id,
                            kind,
                            item.failure.reason,
                            item.failure.failed_at,
                            Json(item.failure.model_dump(mode="json")),
                        ),
                    )
                self._conn.execute(
                    "INSERT INTO normalize_positions (kind, last_seq, updated_at)"
                    " VALUES (%s, %s, %s) ON CONFLICT (kind)"
                    " DO UPDATE SET last_seq = EXCLUDED.last_seq, updated_at = EXCLUDED.updated_at",
                    (kind, last_seq, now),
                )
        except errors.ForeignKeyViolation:
            raise UnknownSourceError(f"a {kind} batch points at a missing {kind} source") from None
        except errors.UniqueViolation:
            raise DuplicateRecordError(
                "a source record in the batch already has an outcome"
            ) from None

    def _reject_other_outcomes(self, table, records, failures) -> None:
        """A failure for a source with a result, or a result for a failed source, is a duplicate."""
        failed = [item.source_record_id for item in failures]
        normalized = [record.source_record_id for record in records]
        clash = self._conn.execute(
            sql.SQL(
                "SELECT EXISTS (SELECT 1 FROM {} WHERE source_record_id = ANY(%s))"
                " OR EXISTS (SELECT 1 FROM normalize_failures WHERE source_record_id = ANY(%s))"
            ).format(sql.Identifier(table)),
            (failed, normalized),
        ).fetchone()[0]
        if clash:
            raise DuplicateRecordError("a source record in the batch already has an outcome")

    def get_normalize_failure(self, source_record_id: str) -> NormalizeFailure | None:
        row = self._one(
            "SELECT record FROM normalize_failures WHERE source_record_id = %s",
            (source_record_id,),
        )
        return validate_contract("NormalizeFailure", row[0]) if row else None

    # Entity branching (box 25)

    def list_alert_records(self, after_seq: int | None, limit: int) -> tuple[StoredAlert, ...]:
        check_limit(limit)
        rows = self._all(
            "SELECT s.seq, a.record FROM alert_records a"
            " JOIN source_records s ON s.source_record_id = a.source_record_id"
            " WHERE s.seq > %s ORDER BY s.seq LIMIT %s",
            (after_seq or 0, limit),
        )
        return tuple(StoredAlert(seq, validate_contract("AlertRecord", rec)) for seq, rec in rows)

    def load_branch_position(self) -> int | None:
        row = self._one("SELECT last_seq FROM branch_position WHERE id = 1", ())
        return row[0] if row else None

    def save_branch_position(self, last_seq: int) -> None:
        with self._conn.transaction():
            row = self._conn.execute(
                "SELECT last_seq FROM branch_position WHERE id = 1 FOR UPDATE"
            ).fetchone()
            check_position(row[0] if row else None, last_seq, "branch")
            self._conn.execute(
                "INSERT INTO branch_position (id, last_seq, updated_at) VALUES (1, %s, %s)"
                " ON CONFLICT (id)"
                " DO UPDATE SET last_seq = EXCLUDED.last_seq, updated_at = EXCLUDED.updated_at",
                (last_seq, self._clock()),
            )

    def merge_duplicate(self, target_alert_id: str, duplicate_alert_id: str, seen_at: int) -> bool:
        check_merge(target_alert_id, duplicate_alert_id)
        try:
            with self._conn.transaction():
                row = self._conn.execute(
                    "SELECT record FROM alert_records WHERE alert_id = %s FOR UPDATE",
                    (target_alert_id,),
                ).fetchone()
                if row is None:
                    raise UnknownRecordError("both alerts must be stored")
                inserted = self._conn.execute(
                    "INSERT INTO alert_dedup_merges"
                    " (duplicate_alert_id, target_alert_id, merged_at) VALUES (%s, %s, %s)"
                    " ON CONFLICT (duplicate_alert_id) DO NOTHING",
                    (duplicate_alert_id, target_alert_id, self._clock()),
                ).rowcount
                if not inserted:
                    return False
                merged = merged_alert(validate_contract("AlertRecord", row[0]), seen_at)
                self._conn.execute(
                    "UPDATE alert_records SET record = %s WHERE alert_id = %s",
                    (Json(merged.model_dump(mode="json")), target_alert_id),
                )
        except errors.ForeignKeyViolation:
            raise UnknownRecordError("both alerts must be stored") from None
        return True

    def save_dedup_representative(self, alert_id: str, dedup_key: str, first_seen: int) -> bool:
        try:
            with self._conn.transaction():
                inserted = self._conn.execute(
                    "INSERT INTO alert_dedup_representatives"
                    " (alert_id, dedup_key, first_seen, created_at) VALUES (%s, %s, %s, %s)"
                    " ON CONFLICT (alert_id) DO NOTHING",
                    (alert_id, dedup_key, first_seen, self._clock()),
                ).rowcount
        except errors.ForeignKeyViolation:
            raise UnknownRecordError("the representative alert must be stored") from None
        return bool(inserted)

    def find_dedup_representative(
        self, dedup_key: str, at: int, window_ms: int, exclude_alert_id: str | None = None
    ) -> str | None:
        check_window(window_ms)
        # first_seen <= at < first_seen + window, written as a range on the index column.
        row = self._one(
            "SELECT alert_id FROM alert_dedup_representatives"
            " WHERE dedup_key = %s AND first_seen <= %s AND first_seen > %s"
            " AND alert_id IS DISTINCT FROM %s"
            " ORDER BY first_seen, alert_id LIMIT 1",
            (dedup_key, at, at - window_ms, exclude_alert_id),
        )
        return row[0] if row else None

    # Retention

    def purge_expired(self, now: int) -> PurgeResult:
        cutoff = retention_cutoff(now, self._retention_days)
        if cutoff is None:
            return PurgeResult(0, 0)
        referenced = (
            "(EXISTS (SELECT 1 FROM alert_records a WHERE a.source_record_id = s.source_record_id)"
            " OR EXISTS (SELECT 1 FROM event_records e"
            " WHERE e.source_record_id = s.source_record_id)"
            " OR EXISTS (SELECT 1 FROM normalize_failures f"
            " WHERE f.source_record_id = s.source_record_id))"
        )
        with self._conn.transaction():
            deleted = self._conn.execute(
                f"DELETE FROM source_records s WHERE ingested_at < %s AND NOT {referenced}",
                (cutoff,),
            ).rowcount
            skipped = self._conn.execute(
                f"SELECT count(*) FROM source_records s WHERE ingested_at < %s AND {referenced}",
                (cutoff,),
            ).fetchone()[0]
        return PurgeResult(deleted, skipped)

    def close(self) -> None:
        # A connection the caller handed over goes back to its pool, not here (#104).
        if self._owns_connection:
            self._conn.close()

    def _one(self, query, params):
        with self._conn.transaction():
            return self._conn.execute(query, params).fetchone()

    def _all(self, query, params):
        with self._conn.transaction():
            return self._conn.execute(query, params).fetchall()


def create_postgres_records(
    settings: Settings,
    environ: Mapping[str, str],
    connection: psycopg.Connection | None = None,
) -> PostgresRecordStore:
    """The ``postgresql.records`` factory: connects with ``[database]`` settings.

    With ``connection`` the store reads through a connection the caller borrowed
    from a pool: it is used as it is and never closed here (#104).
    """
    return PostgresRecordStore(
        connection or connect(settings, environ),
        settings.store.raw_retention_days,
        owns_connection=connection is None,
    )


def create_postgres_readonly_records(
    settings: Settings,
    environ: Mapping[str, str],
    connection: psycopg.Connection | None = None,
) -> PostgresRecordStore:
    """The ``postgresql.readonly_records`` factory: the same store on a read-only connection.

    Reads are identical; every write method fails on the connection, so the tools
    agents call cannot change a record (docs/security-policy.md 4).
    """
    return PostgresRecordStore(
        connection or connect_readonly(settings, environ),
        settings.store.raw_retention_days,
        owns_connection=connection is None,
    )
