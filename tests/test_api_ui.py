"""UI 조회 API: 계약, 원본 기반 페이지, 전체 집계와 오류 경계."""

import json
from pathlib import Path

import psycopg
import pytest
from auth_support import admin_client
from psycopg import sql
from psycopg.types.json import Jsonb

from soc.contracts import to_datetime, validate_contract
from soc.db.migrate import migrate

SEED = json.loads((Path(__file__).parent / "fixtures/api/ui_seed.json").read_text())
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
            validate_contract(name, row)


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
    assert body["ticket"]["alert_ids"] == [] and body["ticket"]["hunt_id"]
    assert ui_client.get("/api/tickets", params={"severity": 6}).json()["items"][0]["severity"] == 6
    first = ui_client.get("/api/tickets", params={"limit": 2}).json()
    second = ui_client.get(
        "/api/tickets", params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()
    assert {x["id"] for x in first["items"]}.isdisjoint(x["id"] for x in second["items"])


@pytest.mark.db
def test_review_is_incident_and_artifacts_are_preserved(ui_client):
    items = ui_client.get("/api/incidents", params={"status": "awaiting_review"}).json()["items"]
    assert len(items) == 1
    body = ui_client.get("/api/incidents/" + items[0]["id"]).json()
    validate_contract("incident", body["incident"])
    assert body["artifacts"] and body["proposals"]
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
