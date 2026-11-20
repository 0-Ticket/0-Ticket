"""L2 Ticket 사이 엔티티 경로를 그래프 후보와 화면용 경로로 만든다."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from soc.contracts import to_epoch_ms, validate_contract
from soc.entities import normalize_entity_value

_OPEN_STATUSES = ("analyzing", "awaiting_review", "human_handling", "held")
_LOWER_TYPES = ("host", "domain", "file_hash", "user")
# 모델 입력이 커지지 않게 후보 하나가 싣는 target host 값의 상한이다(#362).
MAX_TARGET_HOSTS = 10
_GRAPH_QUERY = """
WITH peers AS (
    SELECT i.id AS incident_id, i.updated_at, i.title, i.summary, i.status, i.ticket_ids,
           i.entities AS incident_entities, i.severity, i.assessed_severity, i.analysis_round,
           i.review_round, i.created_at, i.details AS incident_details,
           t.id AS ticket_id, 'alert'::text AS peer_kind, a.id AS peer_id, a.entities
    FROM incidents i
    JOIN tickets t ON t.id = ANY(i.ticket_ids) AND t.status = 'linked'
    JOIN alerts a ON a.id = ANY(t.alert_ids)
    WHERE i.status = ANY(%s) AND i.updated_at BETWEEN %s AND %s
      AND cardinality(i.ticket_ids) < %s
    UNION ALL
    SELECT i.id, i.updated_at, i.title, i.summary, i.status, i.ticket_ids,
           i.entities, i.severity, i.assessed_severity, i.analysis_round,
           i.review_round, i.created_at, i.details,
           t.id, 'hunt'::text, h.id, h.entities
    FROM incidents i
    JOIN tickets t ON t.id = ANY(i.ticket_ids) AND t.status = 'linked' AND t.hunt_id IS NOT NULL
    JOIN hunts h ON h.id = t.hunt_id
    WHERE i.status = ANY(%s) AND i.updated_at BETWEEN %s AND %s
      AND cardinality(i.ticket_ids) < %s
), matches AS (
    SELECT p.*, seed.source_kind, seed.source_id, entity->>'type' AS entity_type,
           entity->>'value' AS entity_value, entity->>'role' AS entity_role
    FROM peers p
    CROSS JOIN jsonb_to_recordset(%s::jsonb) AS seed(
        source_kind text, source_id text, entity_type text, entity_value text, entity_role text
    )
    CROSS JOIN LATERAL jsonb_array_elements(p.entities) AS entity
    WHERE seed.entity_role = 'src' AND entity->>'role' = seed.entity_role
      AND entity->>'type' = seed.entity_type
      AND CASE WHEN seed.entity_type = ANY(%s)
               THEN lower(btrim(entity->>'value')) = seed.entity_value
               -- 마스크 없는 IP끼리는 inet 정규형으로 비교하고 그 밖의 값은 문자열 비교로 되돌린다.
               -- ::inet은 WHEN이 참인 가지에서만 계산돼 잘못된 문자열이 오류를 내지 않는다.
               WHEN seed.entity_type = 'ip'
                    AND position('/' IN btrim(entity->>'value')) = 0
                    AND position('/' IN seed.entity_value) = 0
                    AND pg_input_is_valid(btrim(entity->>'value'), 'inet')
                    AND pg_input_is_valid(seed.entity_value, 'inet')
               THEN btrim(entity->>'value')::inet = seed.entity_value::inet
               ELSE btrim(entity->>'value') = seed.entity_value END
), candidate_incidents AS (
    SELECT incident_id, max(updated_at) AS updated_at
    FROM matches
    GROUP BY incident_id
    ORDER BY max(updated_at) DESC, incident_id
    LIMIT %s
)
SELECT m.* FROM matches m JOIN candidate_incidents c USING (incident_id)
ORDER BY m.updated_at DESC, m.incident_id, m.ticket_id, m.peer_id, m.entity_type, m.entity_value
"""


@dataclass(frozen=True)
class GraphCandidate:
    incident_id: str
    paths: tuple[dict[str, Any], ...]
    incident: dict[str, Any]
    target_hosts: tuple[str, ...] = ()


@dataclass(frozen=True)
class GraphResult:
    candidates: tuple[GraphCandidate, ...]
    coverage: str
    reason: str
    paths: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {"coverage": self.coverage, "reason": self.reason, "paths": list(self.paths)}


def classify_graph(
    ticket_id: str,
    source: dict[str, Any] | tuple[dict[str, Any], ...],
    matches: list[dict[str, Any]],
    *,
    max_candidates: int,
) -> GraphResult:
    """Alert 또는 Hunt 엔티티가 이어 주는 Incident 경로를 만든다.

    matches는 Alert·Hunt 노드만 포함해야 한다. Event는 그래프 연결 근거가 아니다.
    """
    source_list = [source] if isinstance(source, dict) else list(source)
    if not source_list or any(item.get("kind") not in ("alert", "hunt") for item in source_list):
        raise ValueError("그래프 출발 노드는 Alert 또는 Hunt여야 한다")
    if max_candidates < 1:
        raise ValueError("max_candidates는 양수여야 한다")

    sources = {item["id"]: item for item in source_list}
    source_entities = {
        source_id: {
            (item["type"], normalize_entity_value(item["type"], item["value"])): item
            for item in item_source.get("entities", [])
            if item.get("role") == "src"
        }
        for source_id, item_source in sources.items()
    }
    incident_paths: dict[str, list[dict[str, Any]]] = {}
    incident_hosts: dict[str, set[str]] = {}
    all_paths = []
    for match in matches:
        if match.get("kind") not in ("alert", "hunt"):
            continue
        for entity in match.get("entities", []):
            if entity.get("role") != "src":
                continue
            key = (entity["type"], normalize_entity_value(entity["type"], entity["value"]))
            source_ids = (
                [match["source_id"]] if match.get("source_id") in sources else list(sources)
            )
            for source_id in source_ids:
                seed = source_entities[source_id].get(key)
                if seed is None:
                    continue
                path = _path(ticket_id, sources[source_id], match, seed)
                if path not in all_paths:
                    all_paths.append(path)
                paths = incident_paths.setdefault(match["incident_id"], [])
                if path not in paths:
                    paths.append(path)
                incident_hosts.setdefault(match["incident_id"], set()).update(_target_hosts(match))

    if len(incident_paths) > max_candidates:
        return GraphResult((), "incomplete", "candidate_limit", tuple(all_paths))
    incidents = {match["incident_id"]: _incident(match) for match in matches}
    candidates = tuple(
        GraphCandidate(
            incident_id,
            tuple(paths),
            incidents[incident_id],
            tuple(sorted(incident_hosts[incident_id])[:MAX_TARGET_HOSTS]),
        )
        for incident_id, paths in sorted(incident_paths.items())
    )
    reason = "paths_found" if candidates else "no_path"
    return GraphResult(candidates, "complete", reason, tuple(all_paths))


def read_graph(
    conn: psycopg.Connection,
    ticket_id: str,
    sources: tuple[dict[str, Any], ...],
    now: datetime,
    *,
    candidate_window_ms: int,
    max_candidates: int,
    max_incident_tickets: int,
) -> GraphResult:
    """시간 창의 linked Ticket들을 엔티티로 연결한다. Event 테이블은 읽지 않는다."""
    source_entities = [
        {
            "source_kind": source["kind"],
            "source_id": source["id"],
            "entity_type": entity["type"],
            "entity_value": normalize_entity_value(entity["type"], entity["value"]),
            "entity_role": entity["role"],
        }
        for source in sources
        for entity in source["entities"]
        if entity["role"] == "src"
    ]
    if not source_entities:
        return GraphResult((), "complete", "no_path", ())
    cutoff = now - timedelta(milliseconds=candidate_window_ms)
    params = (
        list(_OPEN_STATUSES),
        cutoff,
        now,
        max_incident_tickets,
        list(_OPEN_STATUSES),
        cutoff,
        now,
        max_incident_tickets,
        psycopg.types.json.Jsonb(source_entities),
        list(_LOWER_TYPES),
        max_candidates + 1,
    )
    with conn.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(_GRAPH_QUERY, params).fetchall()
    matches = [_match_row(row) for row in rows]
    # The extra distinct Incident is a sentinel that proves the configured candidate bound was hit.
    incident_ids = list(dict.fromkeys(row["incident_id"] for row in matches))
    result = classify_graph(
        ticket_id,
        sources,
        matches,
        max_candidates=max_candidates,
    )
    if len(incident_ids) > max_candidates:
        return GraphResult((), "incomplete", "candidate_limit", result.paths)
    return result


def _path(
    ticket_id: str,
    source: dict[str, Any],
    match: dict[str, Any],
    entity: dict[str, Any],
) -> dict[str, Any]:
    start_kind = "alert" if source["kind"] == "alert" else "hunt"
    end_kind = match["kind"]
    nodes = [
        {"id": ticket_id, "kind": "ticket"},
        {"id": source["id"], "kind": start_kind},
        {
            "id": f"{entity['type']}:{normalize_entity_value(entity['type'], entity['value'])}",
            "kind": "entity",
            "type": entity["type"],
            "value": normalize_entity_value(entity["type"], entity["value"]),
        },
        {"id": match["id"], "kind": end_kind},
        {"id": match["ticket_id"], "kind": "ticket"},
        {"id": match["incident_id"], "kind": "incident"},
    ]
    relations = [
        f"has_{start_kind}",
        "contains_entity",
        "shares_entity",
        f"has_{end_kind}",
        "belongs_to",
    ]
    return {
        "incident_id": match["incident_id"],
        "ticket_id": match["ticket_id"],
        "nodes": nodes,
        "edges": [
            {"from": nodes[index]["id"], "to": nodes[index + 1]["id"], "kind": relation}
            for index, relation in enumerate(relations)
        ],
    }


def _target_hosts(match: dict[str, Any]) -> set[str]:
    """경로로 연결된 알럿의 target host 값(계정 ID·인스턴스 ID 등)을 정규화해 모은다."""
    return {
        normalize_entity_value("host", entity["value"])
        for entity in match.get("alert_entities", [])
        if entity.get("type") == "host" and entity.get("role") == "target"
    }


def _match_row(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    for field in ("created_at", "updated_at"):
        data[field] = to_epoch_ms(data[field])
    incident = validate_contract(
        "incident",
        {
            "id": data["incident_id"],
            "title": data["title"],
            "summary": data["summary"],
            "status": data["status"],
            "ticket_ids": data["ticket_ids"],
            "entities": data["incident_entities"],
            "severity": data["severity"],
            "assessed_severity": data["assessed_severity"],
            "analysis_round": data["analysis_round"],
            "review_round": data["review_round"],
            "created_at": data["created_at"],
            "updated_at": data["updated_at"],
            "details": data["incident_details"],
        },
    ).model_dump(mode="json")
    data["incident"] = incident
    data["id"] = data["peer_id"]
    data["kind"] = data["peer_kind"]
    # entities는 아래서 매칭된 엔티티 하나로 덮어쓰인다. 환경 비교용 전체 목록은 따로 둔다.
    # Hunt는 제외한다.
    data["alert_entities"] = row["entities"] if data["peer_kind"] == "alert" else []
    data["entities"] = [
        {"type": data["entity_type"], "value": data["entity_value"], "role": data["entity_role"]}
    ]
    return data


def _incident(match: dict[str, Any]) -> dict[str, Any]:
    incident = match.get("incident")
    if incident is not None:
        return incident
    return {
        "id": match["incident_id"],
        "title": match.get("incident_title", ""),
        "ticket_ids": [match["ticket_id"]],
        "created_at": 0,
        "updated_at": 0,
    }
