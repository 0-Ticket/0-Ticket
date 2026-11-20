"""UI 조회 API: 계약, 원본 기반 페이지, 전체 집계와 오류 경계."""

import json
from pathlib import Path

import psycopg
import pytest
from auth_support import admin_client
from psycopg import sql
from psycopg.types.json import Jsonb

from soc.contracts import to_datetime, validate_contract
from soc.contracts.alert import contract_data
from soc.db.migrate import migrate
from soc.normalize.mapping import with_derived_columns, with_derived_event_columns

SEED = json.loads((Path(__file__).parent / "fixtures/api/ui_seed.json").read_text())
SEED["alerts"] = [
    with_derived_columns(row) for row in SEED["alerts"]
]  # 파생 컬럼은 ocsf에서(D-065)
SEED["events"] = [
    with_derived_event_columns(row) for row in SEED["events"]
]  # 파생 컬럼은 ocsf에서(D-068)
CONTRACTS = {
    "raw_records": "raw_record",
    "alerts": "alert",
    "events": "event",
    "tickets": "ticket",
    "incidents": "incident",
    "cases": "case",
    "hunts": "hunt",
    "agent_logs": "agent_log",
    "incident_artifacts": "incident_artifact",
    "incident_proposals": "incident_proposal",
}


def insert_row(conn, table, row):
    times = {
        "time",
        "created_at",
        "updated_at",
        "fetched_at",
        "verified_at",
        "started_at",
        "confirmed_at",
        "resolved_at",
        "last_attempt_at",
    }
    json_fields = {
        "ocsf",
        "assets",
        "triage",
        "timeline",
        "techniques",
        "entities",
        "details",
        "input",
        "output",
    }
    if table == "tickets":
        json_fields.add("verdict")
    values = [
        to_datetime(v)
        if k in times and v is not None
        else Jsonb(v)
        if k in json_fields and v is not None
        else v
        for k, v in row.items()
    ]
    conn.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(",").join(map(sql.Identifier, row)),
            sql.SQL(",").join(sql.Placeholder() * len(row)),
        ),
        values,
    )


def test_ui_fixture_contracts():
    for table, name in CONTRACTS.items():
        for row in SEED[table]:
            validate_contract(name, contract_data(name, row))


@pytest.fixture
def ui_db(temp_database, monkeypatch):
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as conn:
        for table, rows in SEED.items():
            for row in rows:
                insert_row(conn, table, row)
    monkeypatch.setenv("DATABASE_URL", temp_database)
    return temp_database


@pytest.fixture
def ui_client(ui_db):
    return admin_client()


@pytest.mark.db
def test_raw_pages_and_details(ui_client):
    for kind in ("alerts", "events"):
        items = []
        cursor = None
        while True:
            p = {"limit": 2}
            if cursor:
                p["cursor"] = cursor
            r = ui_client.get("/api/" + kind, params=p)
            assert r.status_code == 200, r.text
            items.extend(r.json()["items"])
            cursor = r.json()["next_cursor"]
            if not cursor:
                break
        expected = [r["id"] for r in SEED["raw_records"] if r["kind"] == kind[:-1]]
        assert [x["raw_id"] for x in items] == sorted(expected, reverse=True)
        assert len(set(x["raw_id"] for x in items)) == len(items)
        assert {"pending", "succeeded", "failed"} == {x["normalize_status"] for x in items}
        for item in items:
            assert "original_text" not in item and "ocsf" not in item
            assert item["seed_source"] == "dev-seed-ui"
            r = ui_client.get(f"/api/{kind}/{item['raw_id']}")
            assert r.status_code == 200, r.text
            data = r.json()
            validate_contract("raw_record", data["raw_record"])
            stored = next(
                record for record in SEED["raw_records"] if record["id"] == item["raw_id"]
            )
            assert data["raw_record"]["original_text"] == stored["original_text"]
            if item["record_id"]:
                validate_contract(kind[:-1], data["record"])
                if kind == "alerts":  # OCSF 최상위 + details(D-066)
                    assert "ocsf" not in data["record"]
                    assert data["record"]["details"]["id"] == item["record_id"]
                assert ui_client.get(f"/api/{kind}/{item['record_id']}").json() == data
        failed = ui_client.get("/api/" + kind, params={"status": "failed"}).json()["items"]
        assert len(failed) == 1 and failed[0]["record_id"] is None


@pytest.mark.db
def test_ticket_filters_and_full_detail(ui_client):
    r = ui_client.get("/api/tickets", params={"severity": 0, "origin": "l3"})
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 1
    item = r.json()["items"][0]
    assert item["severity"] == 0 and "verdict" not in item
    body = ui_client.get("/api/tickets/" + item["id"]).json()
    validate_contract("ticket", body["ticket"])
    seeded = next(t["title"] for t in SEED["tickets"] if t["id"] == item["id"])
    assert item["title"] == body["ticket"]["title"] == seeded  # 목록과 상세가 같은 값을 준다
    assert body["ticket"]["alert_ids"] == [] and body["ticket"]["hunt_id"]
    assert ui_client.get("/api/tickets", params={"severity": 6}).json()["items"][0]["severity"] == 6
    first = ui_client.get("/api/tickets", params={"limit": 2}).json()
    second = ui_client.get(
        "/api/tickets", params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()
    assert {x["id"] for x in first["items"]}.isdisjoint(x["id"] for x in second["items"])


@pytest.mark.db
def test_incident_proposals_come_back_as_one_recommendation_list_in_seq_order(ui_client):
    """합쳐진 권고 조치가 seq 순으로 나오고, 옛 구조에서 옮긴 행은 priority·rationale이 null이다."""
    artifacts = {row["id"]: row["incident_id"] for row in SEED["incident_artifacts"]}
    first = ui_client.get(
        "/api/incidents/" + artifacts[SEED["incident_proposals"][0]["artifact_id"]]
    )
    legacy = ui_client.get(
        "/api/incidents/" + artifacts[SEED["incident_proposals"][-1]["artifact_id"]]
    )

    mixed = first.json()["proposals"]
    assert [(p["seq"], p["kind"], p["priority"]) for p in mixed] == [
        (1, "detection", "high"),
        (2, "response", "medium"),
    ]
    assert [p["title"] for p in mixed] == ["자식 프로세스 실행 탐지", "서버 점검"]
    assert all(p["detail"] and p["rationale"] for p in mixed)
    assert "body" not in mixed[0]
    moved = legacy.json()["proposals"]
    assert [(p["priority"], p["rationale"]) for p in moved] == [(None, None)]
    for row in mixed + moved:
        validate_contract("incident_proposal", row)


@pytest.mark.db
def test_review_is_incident_and_artifacts_are_preserved(ui_client, ui_db):
    items = ui_client.get("/api/incidents", params={"status": "awaiting_review"}).json()["items"]
    assert len(items) == 1
    incident_id = items[0]["id"]
    incident = next(row for row in SEED["incidents"] if row["id"] == incident_id)
    ticket_id = incident["ticket_ids"][0]
    graph = {
        "coverage": "incomplete",
        "reason": "candidate_limit",
        "paths": [],
    }
    with psycopg.connect(ui_db) as conn:
        conn.execute(
            "UPDATE tickets SET details = jsonb_set(details, '{l2_branch}', %s) WHERE id = %s",
            (Jsonb(graph), ticket_id),
        )
        conn.execute(
            "UPDATE incidents SET entities = entities || %s WHERE id = %s",
            (
                Jsonb([{"type": "host", "value": "collector.example.com", "role": None}]),
                incident_id,
            ),
        )
    body = ui_client.get("/api/incidents/" + items[0]["id"]).json()
    validate_contract("incident", body["incident"])
    assert {"type": "host", "value": "collector.example.com", "role": None} in body["incident"][
        "entities"
    ]
    assert body["artifacts"] and body["proposals"]
    assert body["ticket_graphs"] == [
        {
            "ticket_id": ticket_id,
            **graph,
        }
    ]
    for row in body["artifacts"]:
        validate_contract("incident_artifact", row)
    for row in body["proposals"]:
        validate_contract("incident_proposal", row)
    cases = ui_client.get("/api/cases").json()["items"]
    assert len(cases) == 1
    body = ui_client.get("/api/cases/" + cases[0]["id"]).json()
    validate_contract("case", body["case"])
    assert body["case"]["incident_id"] != items[0]["id"]


@pytest.mark.db
def test_held_incident_is_filterable_and_visible_on_dashboard(ui_client, ui_db):
    incident_id = SEED["incidents"][0]["id"]
    with psycopg.connect(ui_db) as conn:
        conn.execute("UPDATE incidents SET status = 'held' WHERE id = %s", (incident_id,))

    items = ui_client.get("/api/incidents", params={"status": "held"}).json()["items"]
    dashboard = ui_client.get("/api/dashboard").json()

    assert [item["id"] for item in items] == [incident_id]
    assert dashboard["incident_status"]["held"] == 1
    assert incident_id in {item["id"] for item in dashboard["top_incidents"]}


@pytest.mark.db
def test_dashboard_uses_whole_dataset_and_zero_is_not_fallback(ui_client):
    r = ui_client.get("/api/dashboard")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["flow"]["tickets"] == 8 and d["flow"]["cases"] == 1
    assert d["normalization"]["alert"] == {
        "succeeded": 7,
        "failed": 1,
        "pending": 1,
        "success_ratio": 7 / 8,
    }
    assert d["normalization"]["event"]["succeeded"] == 1
    assert d["ticket_severity"] == {"0": 2, **{str(i): 1 for i in range(1, 7)}}
    assert d["hunting"]["promotion_ratio"] == 1 / 5
    top = d["top_incidents"]
    zero = next(x for x in top if x["status"] == "human_handling")
    assert zero["display_severity"] == 0
    assert len(d["analyzed_incidents"]) == 4


@pytest.mark.parametrize("path", ["alerts", "events", "tickets", "incidents", "cases"])
def test_read_api_rejects_bad_parameters_without_db(path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    c = admin_client()
    for params in ({"limit": 0}, {"limit": 201}, {"cursor": "bad<script>"}, {"status": "bad"}):
        r = c.get("/api/" + path, params=params)
        assert r.status_code == 422, r.text
        assert "bad<script>" not in r.text
    assert c.get("/api/" + path + "/bad").status_code == 404
    assert c.get("/api/" + path).status_code == 503
    assert c.post("/api/" + path).status_code == 405


@pytest.mark.db
def test_empty_dashboard_and_missing_details(temp_database, monkeypatch):
    migrate(temp_database)
    monkeypatch.setenv("DATABASE_URL", temp_database)
    c = admin_client()
    d = c.get("/api/dashboard").json()
    assert d["hunting"]["promotion_ratio"] is None
    assert d["normalization"]["alert"]["success_ratio"] is None
    assert d["top_incidents"] == []
    for path, table in [
        ("alerts", "raw_records"),
        ("events", "events"),
        ("tickets", "tickets"),
        ("incidents", "incidents"),
        ("cases", "cases"),
    ]:
        assert c.get("/api/" + path).json() == {"items": [], "next_cursor": None}
        assert c.get("/api/" + path + "/" + SEED[table][0]["id"]).status_code == 404


# --- #345: Ticket 응답의 연결된 Incident 요약 -------------------------------------------------

INCIDENTS = {i["id"]: i for i in SEED["incidents"]}
TKT = {t["id"][-2:]: t["id"] for t in SEED["tickets"]}
INC = {i["id"][-1]: i["id"] for i in SEED["incidents"]}


def summary(incident_id):
    inc = INCIDENTS[incident_id]
    assessed = inc["assessed_severity"]
    return {
        "id": incident_id,
        "title": inc["title"],
        "status": inc["status"],
        "severity": inc["severity"],
        "assessed_severity": assessed,
        "display_severity": inc["severity"] if assessed is None else assessed,
    }


def ticket_incidents(client):
    """목록과 상세가 같은 값을 주는지 확인하면서 Ticket별 incident를 모은다."""
    items = client.get("/api/tickets", params={"limit": 200}).json()["items"]
    out = {x["id"]: x["incident"] for x in items}
    for ticket_id, incident in out.items():
        assert client.get("/api/tickets/" + ticket_id).json()["incident"] == incident
    return out


def set_ticket_ids(ui_db, incident_id, ticket_ids):
    with psycopg.connect(ui_db, autocommit=True) as conn:
        conn.execute("UPDATE incidents SET ticket_ids=%s WHERE id=%s", (ticket_ids, incident_id))


@pytest.mark.db
def test_ticket_incident_summary_and_representative_incident(ui_client):
    got = ticket_incidents(ui_client)
    # 05는 Incident 1(analyzing)과 4(human_handling), 06은 2와 5에 함께 붙은 시드다.
    # id가 가장 큰 Incident 하나만 준다. 4는 assessed_severity 0이라 폴백하지 않는다.
    assert got[TKT["05"]] == summary(INC["4"])
    assert got[TKT["05"]]["display_severity"] == 0
    assert got[TKT["06"]] == summary(INC["5"])
    assert got[TKT["07"]] == summary(INC["3"])
    unlinked = {TKT[n] for n in ("01", "02", "03", "04", "08")}
    assert {k for k, v in got.items() if v is None} == unlinked


@pytest.mark.db
def test_ticket_incident_follows_ticket_ids_and_ignores_ticket_status(ui_client, ui_db):
    # 운영 코드에는 Ticket을 Incident에서 빼거나 옮기는 동작이 없어 ticket_ids를 직접 바꾼다.
    set_ticket_ids(ui_db, INC["4"], [TKT["08"]])  # 05가 4에서 빠지면 다음으로 큰 1(analyzing)
    got = ticket_incidents(ui_client)
    assert got[TKT["05"]] == summary(INC["1"])
    assert got[TKT["05"]]["assessed_severity"] is None  # 분석 전 임시 제목은 status로 구분한다
    assert got[TKT["05"]]["status"] == "analyzing"
    assert got[TKT["08"]] == summary(INC["4"])  # escalated Ticket도 ticket_ids에 있으면 붙는다
    set_ticket_ids(ui_db, INC["1"], [TKT["04"]])  # 05는 어느 Incident에도 없다
    got = ticket_incidents(ui_client)
    assert got[TKT["05"]] is None
    assert got[TKT["04"]] == summary(INC["1"])
    set_ticket_ids(ui_db, INC["5"], [TKT["06"], TKT["07"]])  # 07이 3에서 5로 옮겨진 쪽이 대표
    assert ticket_incidents(ui_client)[TKT["07"]] == summary(INC["5"])


@pytest.mark.db
def test_ticket_list_query_count_does_not_grow_with_tickets(ui_client, ui_db, monkeypatch):
    from contextlib import contextmanager

    from soc.api import db as api_db

    calls = []
    real = api_db.connect

    class Counting:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, query, *args, **kwargs):
            calls.append(str(query))
            return self._conn.execute(query, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    @contextmanager
    def counting(settings):
        with real(settings) as conn:
            yield Counting(conn)

    monkeypatch.setattr(api_db, "connect", counting)

    def add_tickets(start, count):
        base = next(t for t in SEED["tickets"] if t["id"] == TKT["05"])
        ids = []
        with psycopg.connect(ui_db, autocommit=True) as conn:
            for n in range(start, start + count):
                row = {
                    **base,
                    "id": f"tkt_01a19f93-1266-7000-8000-{n:012d}",
                    "alert_ids": [f"alt_01a19f93-1266-7000-8000-{n:012d}"],
                }
                insert_row(conn, "tickets", row)
                ids.append(row["id"])
            conn.execute(
                "UPDATE incidents SET ticket_ids = ticket_ids || %s WHERE id=%s",
                (ids, INC["3"]),
            )

    def list_queries():
        calls.clear()
        items = ui_client.get("/api/tickets", params={"limit": 200}).json()["items"]
        return len(items), list(calls)

    add_tickets(100, 3)
    few_items, few = list_queries()
    add_tickets(200, 27)
    many_items, many = list_queries()
    assert many_items == few_items + 27
    assert len(few) == len(many) == 2  # 페이지 한 번 + Incident 한 번
    assert "&&" in many[1] and "ticket_ids" in many[1]  # GIN 인덱스를 타는 조건
    assert all(
        x["incident"] == summary(INC["3"])
        for x in ui_client.get("/api/tickets", params={"limit": 200}).json()["items"]
        if x["id"] > TKT["08"]
    )
