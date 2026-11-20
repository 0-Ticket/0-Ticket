"""Ticket·Incident 상세 응답(#365): 원본 Alert 요약과 소속 Ticket 제목(db 마커).

샘플: tests/fixtures/api/ui_seed.json. Ticket 01~07은 Alert 하나씩, Ticket 08은 L3 Ticket이다.
"""

from contextlib import contextmanager

import psycopg
import pytest
from auth_support import admin_client
from psycopg.rows import dict_row
from test_api_ui import INC, SEED, TKT, insert_row

from soc.api import db as api_db
from soc.contracts import to_epoch_ms
from soc.db.migrate import migrate

pytestmark = pytest.mark.db


@pytest.fixture
def detail_db(temp_database, monkeypatch):
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as conn:
        for table, rows in SEED.items():
            for row in rows:
                insert_row(conn, table, row)
    monkeypatch.setenv("DATABASE_URL", temp_database)
    return temp_database


def alert_rows(url):
    with psycopg.connect(url, row_factory=dict_row) as conn:
        return {r["id"]: r for r in conn.execute("SELECT id, title, time, severity FROM alerts")}


def expected(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "time": to_epoch_ms(row["time"]),
        "severity": row["severity"],
    }


def set_alerts(url, ticket_id, alert_ids):
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE tickets SET alert_ids=%s WHERE id=%s", (alert_ids, ticket_id))


def test_ticket_detail_summarizes_its_alert(detail_db):
    rows = alert_rows(detail_db)
    ticket = admin_client().get("/api/tickets/" + TKT["01"]).json()
    (alert_id,) = ticket["ticket"]["alert_ids"]
    assert ticket["alerts"] == [expected(rows[alert_id])]
    assert set(ticket["alerts"][0]) == {"id", "title", "time", "severity"}


def test_alert_summaries_follow_alert_ids_order_and_skip_unknown_ids(detail_db):
    rows = alert_rows(detail_db)
    ids = sorted(rows, reverse=True)[:3]
    unknown = "alt_01a19f93-1266-7000-8000-0000000000ff"
    set_alerts(detail_db, TKT["08"], [ids[1], unknown, ids[0], ids[2]])
    got = admin_client().get("/api/tickets/" + TKT["08"]).json()
    assert [a["id"] for a in got["alerts"]] == [ids[1], ids[0], ids[2]]
    assert got["ticket"]["alert_ids"][1] == unknown  # 원본 목록은 그대로다


def test_ticket_without_alerts_has_an_empty_summary_list(detail_db):
    assert admin_client().get("/api/tickets/" + TKT["08"]).json()["alerts"] == []


def test_alert_strings_come_back_unchanged(detail_db):
    with psycopg.connect(detail_db, autocommit=True) as conn:
        conn.execute("UPDATE alerts SET title=%s", ("<b>x</b> <script>alert(1)</script>",))
    got = admin_client().get("/api/tickets/" + TKT["01"]).json()
    assert got["alerts"][0]["title"] == "<b>x</b> <script>alert(1)</script>"


def test_ticket_detail_query_count_does_not_grow_with_alerts(detail_db, monkeypatch):
    calls: list[str] = []
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
    ids = sorted(alert_rows(detail_db))
    client = admin_client()

    def queries(alert_ids):
        set_alerts(detail_db, TKT["08"], alert_ids)
        calls.clear()
        got = client.get("/api/tickets/" + TKT["08"]).json()
        assert len(got["alerts"]) == len(alert_ids)
        return len(calls)

    one = queries(ids[:1])
    many = queries(ids)
    assert len(ids) >= 5 and one == many


def test_incident_detail_has_the_title_of_each_ticket_in_ticket_ids_order(detail_db):
    titles = {t["id"]: t["title"] for t in SEED["tickets"]}
    got = admin_client().get("/api/incidents/" + INC["1"]).json()
    assert got["tickets"] == [{"id": TKT["05"], "title": titles[TKT["05"]]}]
    ids = [TKT["07"], TKT["05"], TKT["06"]]
    with psycopg.connect(detail_db, autocommit=True) as conn:
        conn.execute("UPDATE incidents SET ticket_ids=%s WHERE id=%s", (ids, INC["1"]))
    got = admin_client().get("/api/incidents/" + INC["1"]).json()
    assert [t["id"] for t in got["tickets"]] == ids
    assert got["incident"]["ticket_ids"] == ids  # 기존 필드는 그대로다
    assert [t["title"] for t in got["tickets"]] == [titles[i] for i in ids]


def test_dashboard_top_incidents_leave_out_confirmed_and_dismissed(detail_db):
    """Top 10 기준(D-077): 분석 중·승인 대기·사람 처리·보류만 대상이고 확정·기각은 뺀다."""
    top = admin_client().get("/api/dashboard").json()["top_incidents"]
    statuses = {INC["1"]: "analyzing", INC["2"]: "awaiting_review", INC["4"]: "human_handling"}
    assert {i["id"]: i["status"] for i in top} == statuses
    assert INC["3"] not in {i["id"] for i in top}  # confirmed
    assert INC["5"] not in {i["id"] for i in top}  # dismissed


def test_dashboard_top_incidents_keep_held_ones(detail_db):
    with psycopg.connect(detail_db, autocommit=True) as conn:
        conn.execute("UPDATE incidents SET status='held' WHERE id=%s", (INC["1"],))
    top = admin_client().get("/api/dashboard").json()["top_incidents"]
    assert {i["id"]: i["status"] for i in top}[INC["1"]] == "held"


def test_waiting_count_is_every_awaiting_review_incident_not_per_user(detail_db):
    """ "승인 대기"는 로그인한 사용자와 무관하게 awaiting_review 전체 수다(D-077)."""
    with psycopg.connect(detail_db, autocommit=True) as conn:
        conn.execute("UPDATE incidents SET status='awaiting_review' WHERE id=%s", (INC["4"],))
    waiting = admin_client().get("/api/dashboard").json()["incident_status"]["awaiting_review"]
    assert waiting == 2
