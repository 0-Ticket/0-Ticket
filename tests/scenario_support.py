"""L2 분류 시나리오(#356) 샘플을 읽고 임시 DB에 채우는 도우미.

샘플은 tests/fixtures/l2/scenarios/cases.json이다. 입력 방식이 두 가지다.
- A: alerts 행의 엔티티를 손으로 적어 직접 넣는다(기존 L2 DB 테스트 방식).
- B: 손으로 만든 원본(ELK hit)을 raw_records에 넣고 soc.normalize 실행으로 alerts 행을 만든다.
"""

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from soc.contracts import to_datetime
from soc.ids import new_id
from soc.normalize.config import Settings
from soc.normalize.mapping import RawRow, Result, alert_row, finding_ocsf, normalize
from soc.normalize.run import run as normalize_run

FILE = Path(__file__).parent / "fixtures" / "l2" / "scenarios" / "cases.json"
DATA = json.loads(FILE.read_text(encoding="utf-8"))
NOW = DATA["now"]
CASES = DATA["cases"]
SETTINGS = Settings(
    batch_size=200, lease_seconds=600, connect_timeout_seconds=5, asset_statement_timeout_ms=5000
)
_INDEX = ".internal.alerts-security.alerts-default-000001"


def entities_of(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """A 입력의 [type, value, role] 목록을 Alert 엔티티 목록으로 바꾼다."""
    return [{"type": t, "value": v, "role": r} for t, v, r in spec["entities"]]


def build_hit(uid: str, spec: dict[str, Any]) -> dict[str, Any]:
    """B 입력 하나로 ELK hit 객체를 만든다. 공통 kibana.alert.* 값에 spec의 source를 더한다."""
    source = {**DATA["common_source"], "kibana.alert.uuid": uid, **copy.deepcopy(spec["source"])}
    return {"_id": uid, "_index": _INDEX, "_source": source}


def all_alert_specs(case: dict[str, Any]) -> list[dict[str, Any]]:
    """케이스의 모든 알럿 spec(이전 Incident의 것과 지금 Ticket의 것)."""
    peers = [a for peer in case["peers"] for t in peer["tickets"] for a in t["alerts"]]
    return [*peers, *case["current"]]


@dataclass
class Built:
    """임시 DB에 채운 케이스의 id 모음."""

    current_ticket_id: str
    incidents: dict[str, str] = field(default_factory=dict)  # 이름 → incident id
    peer_alert_entities: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def _insert(conn: psycopg.Connection, table: str, data: dict[str, Any]) -> None:
    json_columns = {"entities", "assets", "triage", "ocsf", "verdict", "details"}
    time_columns = {"time", "created_at", "updated_at"}
    values = []
    for name, value in data.items():
        if name in time_columns:
            value = to_datetime(value)
        elif name in json_columns and value is not None:
            value = Jsonb(value)
        values.append(value)
    columns = ", ".join(data)
    marks = ", ".join(["%s"] * len(data))
    conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", values)  # table은 상수만


def _raw(conn: psycopg.Connection, kind: str, ref: str, original: dict[str, Any]) -> str:
    raw_id = new_id("raw")
    conn.execute(
        "INSERT INTO raw_records (id, kind, siem_profile, siem_ref, fetched_at, original_text)"
        " VALUES (%s, %s, 'elk-test', %s, %s, %s)",
        (raw_id, kind, ref, to_datetime(NOW), json.dumps(original, ensure_ascii=True)),
    )
    return raw_id


def _alert_a(conn: psycopg.Connection, spec: dict[str, Any], label: str) -> str:
    """A 입력 알럿을 직접 넣고 alert id를 돌려준다."""
    alert_id = new_id("alt")
    raw_id = _raw(conn, "alert", label, {"_id": label, "_source": {}})
    entities = entities_of(spec)
    ocsf = finding_ocsf(
        {"finding_info": {"uid": label, "title": label}, "severity_id": 4}, NOW - 600_000, entities
    )
    _insert(conn, "alerts", alert_row(alert_id, raw_id, ocsf, entities))
    return alert_id


def _alerts_b(conn: psycopg.Connection, items: list[tuple[str, dict[str, Any]]]) -> dict[str, str]:
    """B 입력 알럿들을 raw로 넣고 정규화를 실행해 {라벨: alert id}를 돌려준다."""
    raw_ids = {}
    for label, spec in items:
        raw_ids[label] = _raw(conn, "alert", label, build_hit(label, spec))
    normalize_run(SETTINGS, conn, "scenario-test")
    out = {}
    for label, raw_id in raw_ids.items():
        row = conn.execute(
            "SELECT status, result_id, outcome, source FROM normalize_status WHERE raw_id = %s",
            (raw_id,),
        ).fetchone()
        assert row is not None and row[0] == "succeeded", f"{label}: 정규화 실패"
        assert row[2] in ("ok", "partial"), f"{label}: 폴백이다"
        out[label] = row[1]
    return out


def _ticket(
    conn: psycopg.Connection, case: str, label: str, alert_ids: list[str], status: str
) -> str:
    entities: list[dict[str, Any]] = []
    for alert_id in alert_ids:
        found = conn.execute("SELECT entities FROM alerts WHERE id = %s", (alert_id,)).fetchone()
        entities.extend(found[0])
    ticket_id = new_id("tkt")
    _insert(
        conn,
        "tickets",
        {
            "id": ticket_id,
            "title": f"{case} {label}",
            "origin": "auto",
            "status": status,
            "alert_ids": alert_ids,
            "hunt_id": None,
            "entities": entities,
            "verdict": {
                "decision": "malicious",
                "confidence": 0.9,
                "reason": "시나리오 샘플",
                "evidence_ids": alert_ids,
                "decided_at": NOW - 900_000,
            },
            "created_at": NOW - 7_200_000,
            "updated_at": NOW - 3_600_000,
            "details": {},
        },
    )
    return ticket_id


def _incident(conn: psycopg.Connection, case: str, label: str, ticket_ids: list[str]) -> str:
    incident_id = new_id("inc")
    _insert(
        conn,
        "incidents",
        {
            "id": incident_id,
            "title": f"{case} {label}",
            "summary": None,
            "status": "analyzing",
            "ticket_ids": ticket_ids,
            "entities": [],
            "severity": 4,
            "assessed_severity": None,
            "analysis_round": 0,
            "review_round": 0,
            "created_at": NOW - 7_200_000,
            "updated_at": NOW - 3_600_000,
            "details": {},
        },
    )
    return incident_id


def build_case(conn: psycopg.Connection, case: dict[str, Any]) -> Built:
    """케이스의 이전 Incident·Ticket·Alert와 지금 Ticket(escalated)을 채운다.

    Args:
        conn: 마이그레이션이 끝난 임시 DB 연결(autocommit).
        case: cases.json의 케이스 하나.
    """
    name = case["case"]
    # (라벨, spec) 목록을 만들어 B 입력은 한 번에 정규화한다
    plan: list[tuple[str, list[list[tuple[str, dict[str, Any]]]]]] = []
    for peer in case["peers"]:
        for copy_no in range(peer.get("copies", 1)):
            peer_name = peer["name"] if "copies" not in peer else f"{peer['name']}-{copy_no + 1}"
            tickets = []
            for t_no, ticket in enumerate(peer["tickets"]):
                for t_copy in range(ticket.get("copies", 1)):
                    alerts = []
                    for a_no, spec in enumerate(ticket["alerts"]):
                        label = f"{name}/{peer_name}/{t_no}.{t_copy}/{a_no}"
                        alerts.append((label, spec))
                    tickets.append(alerts)
            plan.append((peer_name, tickets))
    current = [(f"{name}/current/{i}", spec) for i, spec in enumerate(case["current"])]

    b_items = [
        (label, spec)
        for _, tickets in plan
        for alerts in tickets
        for label, spec in alerts
        if "source" in spec
    ] + [(label, spec) for label, spec in current if "source" in spec]
    b_ids = _alerts_b(conn, b_items) if b_items else {}

    def alert_id(label: str, spec: dict[str, Any]) -> str:
        return b_ids[label] if "source" in spec else _alert_a(conn, spec, label)

    built = Built(current_ticket_id="")
    for peer_name, tickets in plan:
        ticket_ids = []
        for alerts in tickets:
            ids = [alert_id(label, spec) for label, spec in alerts]
            ticket_ids.append(_ticket(conn, name, peer_name, ids, "linked"))
        built.incidents[peer_name] = _incident(conn, name, peer_name, ticket_ids)
    current_ids = [alert_id(label, spec) for label, spec in current]
    built.current_ticket_id = _ticket(conn, name, "current", current_ids, "escalated")
    return built


def fill_incident(conn: psycopg.Connection, case: dict[str, Any], incident_id: str) -> None:
    """Incident를 Ticket 10개로 채운다(모델이 고르는 사이 가득 차는 경쟁을 흉내 낸다)."""
    ticket_ids = list(
        conn.execute("SELECT ticket_ids FROM incidents WHERE id = %s", (incident_id,)).fetchone()[0]
    )
    spec = case["peers"][0]["tickets"][0]["alerts"][0]
    while len(ticket_ids) < 10:
        label = f"{case['case']}/fill/{len(ticket_ids)}"
        ticket_ids.append(
            _ticket(conn, case["case"], "fill", [_alert_a(conn, spec, label)], "linked")
        )
    conn.execute("UPDATE incidents SET ticket_ids = %s WHERE id = %s", (ticket_ids, incident_id))


def normalize_spec(spec: dict[str, Any], uid: str = "uid-1") -> Result:
    """B 입력 하나를 DB 없이 정규화한 결과를 돌려준다."""
    return normalize(RawRow(id=new_id("raw"), kind="alert", original=build_hit(uid, spec)))
