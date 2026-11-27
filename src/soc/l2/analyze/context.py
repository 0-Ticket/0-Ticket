"""L2 Incident 분석 문맥과 저장된 분류 그래프를 읽는다."""

from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row

from soc.asset_lookup import AssetLookupError, lookup_assets
from soc.contracts import to_epoch_ms, validate_contract
from soc.contracts.alert import alert_model_input
from soc.contracts.event import event_model_input
from soc.l2.branch.read import _contract_row, _existing_ids, read_branch_data
from soc.l2.config import AnalyzeSettings

# 한 연결(출발 Ticket의 엔티티 → 상대 Ticket)이 모델 입력에 싣는 상대 ID의 상한이다(#396).
MAX_PEER_IDS = 5


def summarize_paths(
    paths: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    max_peer_ids: int = MAX_PEER_IDS,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """저장된 경로를 엔티티 → 상대 Ticket → 상대 ID 연결로 줄인다. 저장된 경로에 있는 것만 쓴다.

    경로 노드는 branch/graph.py `_path`의 순서(Ticket, 출발, 엔티티, 상대, 상대 Ticket, Incident)다.
    상대 ID가 상한을 넘으면 앞에서부터 남기고 `omitted`에 생략 건수를 적는다.
    연결과 `from`은 줄이지 않는다.
    반환하는 둘째 값은 상대 Ticket → Incident다.
    """
    links: dict[str, dict[str, Any]] = {}
    peers: dict[str, str] = {}
    for path in paths:
        source, entity, peer = path["nodes"][1], path["nodes"][2], path["nodes"][3]
        peers.setdefault(path["ticket_id"], path["incident_id"])
        link = links.setdefault(entity["id"], {"entity": entity["id"], "from": [], "to": {}})
        if source["id"] not in link["from"]:
            link["from"].append(source["id"])
        ids = link["to"].setdefault(path["ticket_id"], [])
        if peer["id"] not in ids:
            ids.append(peer["id"])
    result = []
    for link in links.values():
        omitted = {
            t: len(ids) - max_peer_ids for t, ids in link["to"].items() if len(ids) > max_peer_ids
        }
        link["to"] = {t: ids[:max_peer_ids] for t, ids in link["to"].items()}
        result.append({**link, "omitted": omitted} if omitted else link)
    return result, peers


def ticket_graph(
    ticket: dict[str, Any], peers: dict[str, str], *, max_peer_ids: int = MAX_PEER_IDS
) -> dict[str, Any]:
    """Ticket의 저장된 분류 결과(details.l2_branch)를 입력용 그래프 항목으로 읽는다.

    peers에 상대 Ticket → Incident를 더한다.
    """
    branch = ticket["details"].get("l2_branch")
    links, found = summarize_paths(
        [] if branch is None else branch.get("paths", []), max_peer_ids=max_peer_ids
    )
    for peer, incident in found.items():
        peers.setdefault(peer, incident)
    return {
        "ticket_id": ticket["id"],
        "coverage": "legacy" if branch is None else branch.get("coverage", "unknown"),
        "reason": None if branch is None else branch.get("reason"),
        "links": links,
    }


def _without_details(row: dict[str, Any]) -> dict[str, Any]:
    # details는 "계약에 없는 값. 다른 단계는 읽지 않는다"(실행 기록·분류 진행 상태)라 보내지 않는다
    return {key: value for key, value in row.items() if key != "details"}


@dataclass(frozen=True)
class AnalyzeContext:
    incident: dict[str, Any]
    tickets: tuple[dict[str, Any], ...]
    alerts: tuple[dict[str, Any], ...]
    events: tuple[dict[str, Any], ...]
    hunts: tuple[dict[str, Any], ...]
    assets: list[dict[str, Any]]
    ticket_graphs: tuple[dict[str, Any], ...]
    window: dict[str, Any]
    previous_artifact: dict[str, Any] | None
    rejection: dict[str, Any] | None
    evidence_ids: tuple[str, ...]
    asset_lookup_failed: bool
    max_range_days: int
    peer_tickets: dict[str, str] = field(default_factory=dict)

    def investigate_data(self) -> dict[str, Any]:
        return {
            "incident": _without_details(self.incident),
            "tickets": [_without_details(ticket) for ticket in self.tickets],
            "alerts": list(self.alerts),
            "events": list(self.events),
            "hunts": list(self.hunts),
            "assets": self.assets,
            "graph": {"peer_tickets": self.peer_tickets, "tickets": list(self.ticket_graphs)},
            "window": self.window,
            "max_range_days": self.max_range_days,
            "previous_artifact": self.previous_artifact,
            "rejection": self.rejection,
            "asset_lookup_failed": self.asset_lookup_failed,
        }


def calculate_window(
    *,
    earliest_ms: int,
    now_ms: int,
    lookback_ms: int,
) -> dict[str, Any]:
    return {"from": earliest_ms - lookback_ms, "to": now_ms}


def read_context(
    conn: psycopg.Connection,
    incident_id: str,
    settings: AnalyzeSettings,
    *,
    now_ms: int,
    max_range_days: int,
    asset_statement_timeout_ms: int,
) -> AnalyzeContext | None:
    """Incident와 linked Ticket을 읽는다. 읽을 Ticket이 하나도 없으면 None이다."""
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute("SELECT * FROM incidents WHERE id = %s", (incident_id,)).fetchone()
    if row is None:
        return None
    incident = _contract_row("incident", row)
    if incident["status"] != "analyzing":
        return None

    tickets = []
    alerts: dict[str, dict[str, Any]] = {}
    events: dict[str, dict[str, Any]] = {}
    hunts: dict[str, dict[str, Any]] = {}
    ticket_graphs = []
    peer_tickets: dict[str, str] = {}
    evidence: dict[str, None] = {}
    for ticket_id in incident["ticket_ids"]:
        try:
            rows = read_branch_data(conn, ticket_id, expected_status="linked")
        except (LookupError, ValueError):
            continue
        tickets.append(rows.ticket)
        ticket_graphs.append(ticket_graph(rows.ticket, peer_tickets))
        for alert in rows.alerts:
            item = alert_model_input(alert)  # 모델 입력과 시간 창은 이전 모양(start_time 기준)이다
            alerts.setdefault(item["id"], item)
            evidence.setdefault(item["id"], None)
        for event in rows.events:
            item = event_model_input(event)  # 모델 입력과 시간 창은 이전 모양이다
            events.setdefault(item["id"], item)
        if rows.hunt is not None:
            hunts.setdefault(rows.hunt["id"], rows.hunt)
        for evidence_id in rows.evidence_ids:
            evidence.setdefault(evidence_id, None)
    if not tickets:
        return None

    evidence_times = [row["time"] for row in (*alerts.values(), *events.values())]
    window = calculate_window(
        earliest_ms=min(evidence_times, default=min(ticket["created_at"] for ticket in tickets)),
        now_ms=now_ms,
        lookback_ms=settings.lookback_ms,
    )
    try:
        assets = lookup_assets(conn, incident["entities"], asset_statement_timeout_ms)
        asset_failed = False
    except AssetLookupError:
        assets, asset_failed = [], True
    previous_artifact = _previous_artifact(conn, incident_id)
    if previous_artifact is not None:
        previous_ids = previous_artifact["evidence_ids"]
        existing = set()
        for prefix, table in (("alt_", "alerts"), ("evt_", "events"), ("agl_", "agent_logs")):
            existing |= _existing_ids(
                conn, table, [item for item in previous_ids if item.startswith(prefix)]
            )
        for evidence_id in previous_ids:
            if evidence_id in existing:
                evidence.setdefault(evidence_id, None)
    return AnalyzeContext(
        incident=incident,
        tickets=tuple(tickets),
        alerts=tuple(alerts.values()),
        events=tuple(events.values()),
        hunts=tuple(hunts.values()),
        assets=assets,
        ticket_graphs=tuple(ticket_graphs),
        window=window,
        previous_artifact=previous_artifact,
        rejection=_latest_rejection(conn, incident_id),
        evidence_ids=tuple(evidence),
        asset_lookup_failed=asset_failed,
        max_range_days=max_range_days,
        peer_tickets=peer_tickets,
    )


def _previous_artifact(conn: psycopg.Connection, incident_id: str) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "SELECT * FROM incident_artifacts WHERE incident_id = %s "
            "ORDER BY analysis_round DESC LIMIT 1",
            (incident_id,),
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["created_at"] = to_epoch_ms(data["created_at"])
    return validate_contract("incident_artifact", data).model_dump(mode="json")


def _latest_rejection(conn: psycopg.Connection, incident_id: str) -> dict[str, Any] | None:
    """가장 최근 검토가 반려이고 그 뒤에 성공한 Artifact가 아직 없을 때만 사유(또는 사실)를 낸다.

    실패한 재시도는 Artifact가 없어 사유가 유지되고, 성공한 재분석이나 승인 뒤에는 나오지 않는다.
    사유는 사람이 쓴 문장이라 호출하는 쪽이 데이터로만 넘긴다(D-082).
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "SELECT r.reason, r.created_at FROM incident_reviews r "
            "WHERE r.incident_id = %s AND r.decision = 'reject' "
            "AND r.id = (SELECT max(id) FROM incident_reviews WHERE incident_id = %s) "
            "AND NOT EXISTS (SELECT 1 FROM incident_artifacts a "
            "WHERE a.incident_id = r.incident_id AND a.analysis_round > r.analysis_round)",
            (incident_id, incident_id),
        ).fetchone()
    if row is None:
        return None
    return {"reason": row["reason"], "decided_at": to_epoch_ms(row["created_at"])}
