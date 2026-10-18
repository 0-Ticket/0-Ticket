"""PostgreSQL table queue (box 26, D-034, registered as ``postgresql`` in evidence_queues).

``claim_next`` takes the oldest pending row with ``FOR UPDATE SKIP LOCKED`` and
marks it in_progress in the same transaction. A row is claimed once even if two
workers ask at the same time. Every method runs in its own transaction, so a
read never leaves one open on a shared connection.
"""

import json
from collections.abc import Mapping
from typing import Any

import psycopg

from soc.config import Settings
from soc.contracts import validate_contract
from soc.db import connect

from .base import ClaimedRequest, DuplicateRequestError, RequestNotFoundError, RequestStateError


def _request(value: Mapping[str, Any]) -> dict[str, Any]:
    return validate_contract("EvidenceRequest", dict(value)).model_dump(mode="json")


def _decode(payload: Any) -> dict[str, Any]:
    return _request(json.loads(payload) if isinstance(payload, str) else payload)


def _json(request: Mapping[str, Any]) -> str:
    return json.dumps(request, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class PostgresEvidenceQueue:
    def __init__(self, connection: psycopg.Connection, *, owns_connection: bool = False):
        self._connection = connection
        self._owns_connection = owns_connection

    def enqueue(self, request: Mapping[str, Any], *, agent: str) -> dict[str, Any]:
        validated = _request(request)
        try:
            with self._connection.transaction():
                self._connection.execute(
                    """
                    INSERT INTO evidence_requests
                        (request_id, agent, status, requester_type, requester_id, payload)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        validated["request_id"],
                        agent,
                        validated["status"],
                        validated["requester_type"],
                        validated["requester_id"],
                        _json(validated),
                    ),
                )
        except psycopg.errors.UniqueViolation:
            raise DuplicateRequestError("request already queued") from None
        return validated

    def claim_next(self, *, now_ms: int) -> ClaimedRequest | None:
        with self._connection.transaction():
            row = self._connection.execute(
                """
                WITH next AS (
                    SELECT request_id FROM evidence_requests
                    WHERE status = 'pending'
                    ORDER BY seq
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE evidence_requests AS queued
                SET status = 'in_progress',
                    payload = queued.payload
                        || jsonb_build_object('status', 'in_progress', 'updated_at', %s::bigint)
                FROM next
                WHERE queued.request_id = next.request_id
                RETURNING queued.payload, queued.agent
                """,
                (now_ms,),
            ).fetchone()
        if row is None:
            return None
        return ClaimedRequest(_decode(row[0]), row[1])

    def update(self, request: Mapping[str, Any], *, expected_status: str) -> dict[str, Any]:
        validated = _request(request)
        request_id = validated["request_id"]
        with self._connection.transaction():
            row = self._connection.execute(
                "SELECT status FROM evidence_requests WHERE request_id = %s FOR UPDATE",
                (request_id,),
            ).fetchone()
            if row is None:
                raise RequestNotFoundError("request not found")
            if row[0] != expected_status:
                raise RequestStateError("request status changed before update")
            self._connection.execute(
                """
                UPDATE evidence_requests
                SET status = %s, requester_type = %s, requester_id = %s, payload = %s::jsonb
                WHERE request_id = %s
                """,
                (
                    validated["status"],
                    validated["requester_type"],
                    validated["requester_id"],
                    _json(validated),
                    request_id,
                ),
            )
        return validated

    def release_in_progress(self, *, now_ms: int) -> int:
        with self._connection.transaction():
            cursor = self._connection.execute(
                """
                UPDATE evidence_requests
                SET status = 'pending',
                    payload = payload
                        || jsonb_build_object('status', 'pending', 'updated_at', %s::bigint)
                WHERE status = 'in_progress'
                """,
                (now_ms,),
            )
            return cursor.rowcount

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self._connection.transaction():
            row = self._connection.execute(
                "SELECT payload FROM evidence_requests WHERE request_id = %s", (request_id,)
            ).fetchone()
        return None if row is None else _decode(row[0])

    def list_by_requester(self, requester_type: str, requester_id: str) -> list[dict[str, Any]]:
        with self._connection.transaction():
            rows = self._connection.execute(
                """
                SELECT payload FROM evidence_requests
                WHERE requester_type = %s AND requester_id = %s
                ORDER BY seq
                """,
                (requester_type, requester_id),
            ).fetchall()
        return [_decode(row[0]) for row in rows]

    def close(self) -> None:
        if self._owns_connection:
            self._connection.close()


def create_postgresql_evidence_queue(
    settings: Settings, environ: Mapping[str, str] | None = None
) -> PostgresEvidenceQueue:
    """Factory registered as ``postgresql`` in the ``evidence_queues`` registry."""
    return PostgresEvidenceQueue(connect(settings, environ), owns_connection=True)
