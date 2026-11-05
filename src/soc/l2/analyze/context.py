"""L2 Incident 분석 문맥과 같은 조회 구간의 관련 기록을 읽는다."""

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from soc.asset_lookup import AssetLookupError, lookup_assets
from soc.contracts import to_datetime, to_epoch_ms, validate_contract
from soc.entities import normalize_entity_value
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
    related: tuple[dict[str, Any], ...]
    window: dict[str, Any]
    previous_artifact: dict[str, Any] | None
    evidence_ids: tuple[str, ...]
    asset_lookup_failed: bool

    def investigate_data(self) -> dict[str, Any]:
        return {
            "incident": self.incident,
            "tickets": list(self.tickets),
            "alerts": list(self.alerts),
            "events": list(self.events),
            "hunts": list(self.hunts),
            "assets": self.assets,
            "related": list(self.related),
            "window": self.window,
            "previous_artifact": self.previous_artifact,
            "asset_lookup_failed": self.asset_lookup_failed,
        }


def calculate_window(
    *,
    earliest_ticket_ms: int,
    now_ms: int,
    lookback_ms: int,
    max_range_days: int,
) -> dict[str, Any]:
    requested = earliest_ticket_ms - lookback_ms
    floor = now_ms - max_range_days * 86_400_000
    start = max(requested, floor)
    return {
        "from": start,
        "to": now_ms,
        "truncated": start > requested,
        "requested_from": requested,
    }


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
    evidence: dict[str, None] = {}
    for ticket_id in incident["ticket_ids"]:
        try:
            rows = read_branch_data(conn, ticket_id, expected_status="linked")
        except (LookupError, ValueError):
            continue
        tickets.append(rows.ticket)
        for alert in rows.alerts:
            alerts.setdefault(alert["id"], alert)
            evidence.setdefault(alert["id"], None)
        for event in rows.events:
            events.setdefault(event["id"], event)
        if rows.hunt is not None:
            hunts.setdefault(rows.hunt["id"], rows.hunt)
        for evidence_id in rows.evidence_ids:
            evidence.setdefault(evidence_id, None)
    if not tickets:
        return None

    window = calculate_window(
        earliest_ticket_ms=min(ticket["created_at"] for ticket in tickets),
        now_ms=now_ms,
        lookback_ms=settings.lookback_ms,
        max_range_days=max_range_days,
    )
    try:
        assets = lookup_assets(conn, incident["entities"], asset_statement_timeout_ms)
        asset_failed = False
    except AssetLookupError:
        assets, asset_failed = [], True
    related = _related(conn, incident["entities"][: settings.max_seed_entities], window, settings)
    for item in related:
        evidence.setdefault(item["record"]["id"], None)
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
        related=related,
        window=window,
        previous_artifact=previous_artifact,
        evidence_ids=tuple(evidence),
        asset_lookup_failed=asset_failed,
    )


def _related(
    conn: psycopg.Connection,
    entities: list[dict[str, Any]],
    window: dict[str, Any],
    settings: AnalyzeSettings,
) -> tuple[dict[str, Any], ...]:
    found: dict[tuple[str, str], dict[str, Any]] = {}
    start, end = to_datetime(window["from"]), to_datetime(window["to"])
    for entity in entities:
        value = normalize_entity_value(entity["type"], entity["value"])
        rows = []
        for kind, table in (("alert", "alerts"), ("event", "events")):
            with conn.cursor(row_factory=dict_row) as cursor:
                fetched = cursor.execute(
                    f"SELECT * FROM {table} WHERE time BETWEEN %s AND %s "
                    "AND EXISTS (SELECT 1 FROM jsonb_array_elements(entities) item "
                    "WHERE item->>'type' = %s AND item->>'value' = %s) "
                    "ORDER BY time DESC LIMIT %s",
                    (start, end, entity["type"], value, settings.max_related_per_entity),
                ).fetchall()
            rows.extend((kind, row) for row in fetched)
        rows.sort(key=lambda item: item[1]["time"], reverse=True)
        for kind, row in reversed(rows[: settings.max_related_per_entity]):
            record = _contract_row(kind, row)
            found.setdefault((kind, record["id"]), {"kind": kind, "record": record})
    return tuple(sorted(found.values(), key=lambda item: item["record"]["time"]))


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
