"""Qdrant의 유사 Ticket을 PostgreSQL의 열린 Incident 후보로 검증한다."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from soc.entities import normalize_entity_value
from soc.l2.branch.read import _contract_row
from soc.l2.branch.runtime import BranchService
from soc.l2.branch.store import _INCIDENT_COLUMNS
from soc.store.qdrant import SearchHit

_OPEN = ("analyzing", "awaiting_review", "human_handling", "held")
_PAGE = 100


@dataclass(frozen=True)
class VectorCandidate:
    incident: dict[str, Any]
    ticket_id: str
    score: float
    target_hosts: tuple[str, ...]


def index_ready(conn: psycopg.Connection, service: BranchService) -> bool:
    """백필·미처리·컬렉션 재생성·누락 point를 후보 0건과 구분한다."""
    row = conn.execute(
        """SELECT count(*), count(*) FILTER (WHERE j.ticket_id IS NULL OR
        j.revision > j.indexed_revision), count(*) FILTER (WHERE j.failed_revision = j.revision)
        FROM tickets t LEFT JOIN l2_ticket_index_jobs j ON j.ticket_id = t.id"""
    ).fetchone()
    assert row is not None
    total, pending, failed = row
    if failed:
        raise RuntimeError("ticket_index_write_failed")
    if pending or not service.store.exists():
        return False
    return service.store.count() == total


def find_candidates(
    conn: psycopg.Connection,
    service: BranchService,
    text: str,
    ticket_id: str,
    *,
    min_score: float,
    max_incident_tickets: int,
) -> tuple[VectorCandidate, ...]:
    """하한 이상인 모든 point를 읽고 현재 DB 소속으로 검증한다."""
    vector = service.embedder.embed(text)
    hits = _search_all(service, vector, min_score)
    ranked: dict[str, VectorCandidate] = {}
    for start in range(0, len(hits), _PAGE):
        page = hits[start : start + _PAGE]
        ids = [f"tkt_{hit.point_id}" for hit in page if f"tkt_{hit.point_id}" != ticket_id]
        if ids:
            with conn.cursor(row_factory=dict_row) as cur:
                rows = cur.execute(
                    """SELECT t.id AS ticket_id,
                    j.revision, j.indexed_revision, i.*
                    FROM tickets t
                    JOIN l2_ticket_index_jobs j ON j.ticket_id = t.id
                    JOIN incidents i ON t.id = ANY(i.ticket_ids)
                    WHERE t.id = ANY(%s) AND t.status = 'linked'
                      AND i.status = ANY(%s) AND cardinality(i.ticket_ids) < %s""",
                    (ids, list(_OPEN), max_incident_tickets),
                ).fetchall()
            hits = {f"tkt_{hit.point_id}": hit for hit in page}
            for row in rows:
                hit = hits[row["ticket_id"]]
                if row["indexed_revision"] != row["revision"]:
                    continue
                if (
                    hit.payload.get("revision") != row["revision"]
                    or hit.payload.get("linked") is not True
                ):
                    continue
                incident = _contract_row(
                    "incident", {column: row[column] for column in _INCIDENT_COLUMNS}
                )
                found = ranked.get(incident["id"])
                if found is None or hit.score > found.score:
                    ranked[incident["id"]] = VectorCandidate(
                        incident,
                        row["ticket_id"],
                        hit.score,
                        _target_hosts(conn, incident["ticket_ids"]),
                    )
    return tuple(sorted(ranked.values(), key=lambda item: (-item.score, item.incident["id"])))


def _search_all(
    service: BranchService, vector: Sequence[float], min_score: float
) -> tuple[SearchHit, ...]:
    """동점으로 offset 페이지가 겹치면 전체 결과를 다시 읽어 누락을 막는다."""
    offset = 0
    hits: dict[str, SearchHit] = {}
    while True:
        page = service.store.search(
            vector, _PAGE, {"linked": True}, offset=offset, score_threshold=min_score
        )
        offset += len(page)
        hits.update((hit.point_id, hit) for hit in page)
        if len(page) < _PAGE:
            break
    if len(hits) < offset:
        # Qdrant는 동점 결과의 offset 페이지에서 같은 point를 다시 줄 수 있다.
        return service.store.search(
            vector, max(1, service.store.count()), {"linked": True}, score_threshold=min_score
        )
    return tuple(hits.values())


def _target_hosts(conn: psycopg.Connection, ticket_ids: list[str]) -> tuple[str, ...]:
    rows = conn.execute(
        """SELECT a.entities FROM alerts a JOIN tickets t ON a.id = ANY(t.alert_ids)
        WHERE t.id = ANY(%s) ORDER BY a.id LIMIT 20""",
        (ticket_ids,),
    ).fetchall()
    return tuple(
        sorted(
            {
                normalize_entity_value("host", entity["value"])
                for (entities,) in rows
                for entity in entities
                if entity.get("type") == "host" and entity.get("role") == "target"
            }
        )[:10]
    )
