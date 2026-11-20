"""Incident 승인·반려 API(#365, D-076).

권한·형식 검사는 DB 없이, 상태 전이와 Case 생성은 db 마커로 본다.

샘플: tests/fixtures/api/ui_seed.json(손으로 만든 시드). Incident 2가 awaiting_review다.
"""

import threading

import psycopg
import pytest
from auth_support import ORIGIN, admin_client, make_client, make_user
from psycopg.rows import dict_row
from test_api_ui import INC, SEED, insert_row

from soc.api.app import create_app
from soc.api.auth import session_user
from soc.api.config import load_settings
from soc.auth.permissions import ANALYST_DEFAULT, PERMISSIONS
from soc.contracts import validate_contract
from soc.contracts.alert import contract_data
from soc.db.migrate import migrate

REVIEW = INC["2"]
UNKNOWN = "inc_01a19f93-1266-7000-8000-0000000000ff"
ACTIONS = ("approve", "reject")


def post(client, incident_id, action):
    return client.post(f"/api/incidents/{incident_id}/{action}")


# 권한·형식(DB 없음)


@pytest.mark.parametrize("action", ACTIONS)
def test_analyst_without_the_permission_is_denied(action):
    analyst = make_user("analyst", frozenset(ANALYST_DEFAULT))
    r = post(make_client(analyst), REVIEW, action)
    assert (r.status_code, r.json()) == (403, {"error": "permission_denied"})


@pytest.mark.parametrize("action", ACTIONS)
def test_each_action_needs_its_own_permission(action):
    other = "incident.reject" if action == "approve" else "incident.approve"
    user = make_user("analyst", frozenset({*ANALYST_DEFAULT, other}))
    assert post(make_client(user), REVIEW, action).status_code == 403


@pytest.mark.parametrize("action", ACTIONS)
def test_unauthenticated_request_is_401(action):
    client = make_client()
    assert post(client, REVIEW, action).status_code == 401


@pytest.mark.parametrize("action", ACTIONS)
def test_foreign_origin_is_refused(action):
    client = make_client(make_user("admin"))
    r = client.post(f"/api/incidents/{REVIEW}/{action}", headers={"origin": "http://evil.example"})
    assert (r.status_code, r.json()) == (403, {"error": "origin_not_allowed"})


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("bad", ["x", "tkt_01a19f93-1266-7000-8000-000000000001", "inc_1"])
def test_malformed_id_is_404_before_any_db_access(action, bad, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)  # DB를 건드리면 503이 된다
    assert post(admin_client(), bad, action).status_code == 404


@pytest.mark.parametrize("action", ACTIONS)
def test_review_routes_have_no_body_and_ignore_extra_fields(action, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    r = admin_client().post(f"/api/incidents/{REVIEW}/{action}", json={"reason": "x"})
    assert r.status_code == 503  # 본문은 읽지 않는다. 사유 입력은 없다


def test_approval_permissions_are_used_by_routes_and_close_is_not():
    from soc.api import auth as api_auth
    from soc.auth.permissions import UNUSED

    create_app(load_settings())
    assert {"incident.approve", "incident.reject"} <= api_auth.USED_PERMISSIONS
    assert UNUSED == {"incident.close"}
    assert set(PERMISSIONS) - api_auth.USED_PERMISSIONS == UNUSED


# 상태 전이와 Case 생성(DB)


@pytest.fixture
def review_db(temp_database, monkeypatch):
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as conn:
        for table, rows in SEED.items():
            for row in rows:
                insert_row(conn, table, row)
    monkeypatch.setenv("DATABASE_URL", temp_database)
    return temp_database


def q(url, query, *args):
    with psycopg.connect(url, row_factory=dict_row) as conn:
        return conn.execute(query, args).fetchall()


def incident(url, incident_id):
    return q(url, "SELECT * FROM incidents WHERE id=%s", incident_id)[0]


def cases_of(url, incident_id):
    return q(url, "SELECT * FROM cases WHERE incident_id=%s", incident_id)


@pytest.mark.db
def test_approve_confirms_the_incident_and_creates_one_open_case(review_db):
    before = incident(review_db, REVIEW)
    r = post(admin_client(), REVIEW, "approve")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["incident"]["id"] == REVIEW and body["incident"]["status"] == "confirmed"
    after = incident(review_db, REVIEW)
    assert after["status"] == "confirmed" and after["updated_at"] > before["updated_at"]
    assert after["review_round"] == before["review_round"]
    assert after["analysis_round"] == before["analysis_round"]
    (case,) = cases_of(review_db, REVIEW)
    assert body["case_id"] == case["id"] and case["id"].startswith("cas_")
    assert (case["title"], case["summary"], case["entities"]) == (
        before["title"],
        before["summary"],
        before["entities"],
    )
    assert case["severity"] == before["assessed_severity"] == 5
    assert (case["confirmed_by"], case["status"]) == ("tester", "open")
    assert case["assignee"] is None and case["resolved_at"] is None and case["details"] == {}
    assert case["confirmed_at"] is not None
    row = {**case, "confirmed_at": int(case["confirmed_at"].timestamp() * 1000)}
    validate_contract("case", contract_data("case", row))


@pytest.mark.db
def test_case_severity_falls_back_to_incident_severity_without_assessment(review_db):
    with psycopg.connect(review_db, autocommit=True) as conn:
        conn.execute(
            "UPDATE incidents SET assessed_severity=NULL, severity=3 WHERE id=%s", (REVIEW,)
        )
    assert post(admin_client(), REVIEW, "approve").status_code == 200
    assert cases_of(review_db, REVIEW)[0]["severity"] == 3


@pytest.mark.db
def test_assessed_severity_zero_is_not_replaced_by_the_fallback(review_db):
    with psycopg.connect(review_db, autocommit=True) as conn:
        conn.execute("UPDATE incidents SET assessed_severity=0, severity=4 WHERE id=%s", (REVIEW,))
    assert post(admin_client(), REVIEW, "approve").status_code == 200
    assert cases_of(review_db, REVIEW)[0]["severity"] == 0


@pytest.mark.db
def test_approved_case_shows_up_in_case_list_and_dashboard(review_db):
    client = admin_client()
    cases_before = client.get("/api/cases").json()["items"]
    waiting_before = client.get("/api/dashboard").json()["incident_status"]["awaiting_review"]
    case_id = post(client, REVIEW, "approve").json()["case_id"]
    items = client.get("/api/cases").json()["items"]
    assert len(items) == len(cases_before) + 1 and case_id in {x["id"] for x in items}
    dash = client.get("/api/dashboard").json()
    assert dash["incident_status"]["awaiting_review"] == waiting_before - 1
    assert REVIEW not in {x["id"] for x in dash["top_incidents"]}  # 확정은 Top 10에서 빠진다(D-077)


@pytest.mark.db
def test_reject_sends_the_incident_back_to_analyzing_without_a_case(review_db):
    before = incident(review_db, REVIEW)
    r = post(admin_client(), REVIEW, "reject")
    assert r.status_code == 200, r.text
    assert r.json()["incident"]["status"] == "analyzing" and r.json()["case_id"] is None
    after = incident(review_db, REVIEW)
    assert after["status"] == "analyzing" and after["updated_at"] > before["updated_at"]
    # review_round·한도는 이번 범위가 아니다(별도 이슈). 다른 값은 그대로다
    for key in ("review_round", "analysis_round", "title", "summary", "entities", "details"):
        assert after[key] == before[key]
    assert cases_of(review_db, REVIEW) == []


@pytest.mark.db
@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize(
    ("number", "status"),
    [("1", "analyzing"), ("3", "confirmed"), ("4", "human_handling"), ("5", "dismissed")],
)
def test_other_states_answer_409_with_the_current_state_and_change_nothing(
    review_db, action, number, status
):
    target = INC[number]
    before = incident(review_db, target)
    n_cases = len(q(review_db, "SELECT id FROM cases"))
    r = post(admin_client(), target, action)
    assert (r.status_code, r.json()) == (
        409,
        {"error": "incident_not_awaiting_review", "status": status},
    )
    assert incident(review_db, target) == before
    assert len(q(review_db, "SELECT id FROM cases")) == n_cases


@pytest.mark.db
@pytest.mark.parametrize("action", ACTIONS)
def test_unknown_incident_is_404(review_db, action):
    assert post(admin_client(), UNKNOWN, action).status_code == 404


@pytest.mark.db
def test_second_request_is_refused_and_does_not_make_a_second_case(review_db):
    client = admin_client()
    assert post(client, REVIEW, "approve").status_code == 200
    r = post(client, REVIEW, "approve")
    assert (r.status_code, r.json()["status"]) == (409, "confirmed")
    assert post(client, REVIEW, "reject").status_code == 409  # 확정한 것을 반려로 되돌리지 못한다
    assert len(cases_of(review_db, REVIEW)) == 1


@pytest.mark.db
def test_rejected_incident_cannot_be_approved_before_it_is_reviewed_again(review_db):
    client = admin_client()
    assert post(client, REVIEW, "reject").status_code == 200
    r = post(client, REVIEW, "approve")
    assert (r.status_code, r.json()["status"]) == (409, "analyzing")


@pytest.mark.db
@pytest.mark.parametrize(
    "pair", [("approve", "approve"), ("approve", "reject"), ("reject", "approve")]
)
def test_simultaneous_requests_let_exactly_one_through(review_db, pair):
    results: list[int] = []
    gate = threading.Barrier(2)

    def run(action):
        app = create_app(load_settings())
        app.dependency_overrides[session_user] = lambda: make_user("admin")
        from starlette.testclient import TestClient

        client = TestClient(app, headers={"origin": ORIGIN})
        gate.wait()
        results.append(post(client, REVIEW, action).status_code)

    threads = [threading.Thread(target=run, args=(a,)) for a in pair]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 409]
    final = incident(review_db, REVIEW)["status"]
    n_cases = len(cases_of(review_db, REVIEW))
    assert (final, n_cases) in {("confirmed", 1), ("analyzing", 0)}
    assert (final == "confirmed") == (n_cases == 1)
