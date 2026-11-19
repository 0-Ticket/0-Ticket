"""L2 Incident 분석 문맥과 저장된 분류 그래프를 읽는다."""

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from soc.asset_lookup import AssetLookupError, lookup_assets
from soc.contracts import to_epoch_ms, validate_contract
from soc.contracts.alert import alert_model_input
from soc.contracts.event import event_model_input
from soc.l2.branch.read import _contract_row, _existing_ids, read_branch_data
from soc.l2.config import AnalyzeSettings


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
    evidence_ids: tuple[str, ...]
    asset_lookup_failed: bool
    max_range_days: int

    def investigate_data(self) -> dict[str, Any]:
        return {
            "incident": self.incident,
            "tickets": list(self.tickets),
            "alerts": list(self.alerts),
            "events": list(self.events),
            "hunts": list(self.hunts),
            "assets": self.assets,
            "graph": {"tickets": list(self.ticket_graphs)},
            "window": self.window,
            "max_range_days": self.max_range_days,
            "previous_artifact": self.previous_artifact,
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
    evidence: dict[str, None] = {}
    for ticket_id in incident["ticket_ids"]:
        try:
            rows = read_branch_data(conn, ticket_id, expected_status="linked")
        except (LookupError, ValueError):
            continue
        tickets.append(rows.ticket)
        branch = rows.ticket["details"].get("l2_branch")
        ticket_graphs.append(
            {
                "ticket_id": ticket_id,
                "coverage": "legacy" if branch is None else branch.get("coverage", "unknown"),
                "reason": None if branch is None else branch.get("reason"),
                "paths": [] if branch is None else branch.get("paths", []),
            }
        )
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
        evidence_ids=tuple(evidence),
        asset_lookup_failed=asset_failed,
        max_range_days=max_range_days,
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
