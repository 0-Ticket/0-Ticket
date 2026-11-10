"""화면용 API의 응답을 실제 PostgreSQL로 확인한다(#239, db 마커).

샘플(tests/fixtures/api/seed.json): 두 가설 생성 run의 Hunt 5건(상태 5가지),
confirmed Hunt의 L3 Ticket, Agent Log(가설 생성 run, 실패·성공 검증 run, 다른 대상의 run),
뉴스 5건, 두 버전의 ATT&CK 기법.
"""

import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from auth_support import admin_client
from psycopg import sql
from psycopg.types.json import Jsonb
from starlette.testclient import TestClient

from soc.api import db as api_db
from soc.api.config import load_settings
from soc.contracts import to_datetime, validate_contract
from soc.db.migrate import migrate
from soc.ids import new_id

pytestmark = pytest.mark.db

SEED = json.loads(
    (Path(__file__).parent / "fixtures" / "api" / "seed.json").read_text(encoding="utf-8")
)
H1, H2, H3, H4, H5 = (h["id"] for h in SEED["hunts"])
HRN_A, HRN_B = SEED["hunts"][0]["hunt_run_id"], SEED["hunts"][4]["hunt_run_id"]
TICKET = SEED["tickets"][0]["id"]
RUNS = sorted({row["run_id"] for row in SEED["agent_logs"]})
T0 = SEED["hunts"][0]["created_at"]
H = 3_600_000
D = 24 * H
MARKER = "AGENT-LOG-RAW-MARKER"

TIMES = {"published_at", "fetched_at", "updated_at", "created_at", "verified_at", "started_at"}
JSONB = {"entities", "details", "input", "output", "verdict"}
TABLES = ("hunts", "tickets", "agent_logs", "threat_news", "attack_techniques")

LIST_KEYS = {
    "id",
    "hunt_run_id",
    "status",
    "hypothesis",
    "attack_techniques",
    "confidence",
    "attempts",
    "verified_at",
    "created_at",
    "updated_at",
}
NEWS_KEYS = {
    "id",
    "source",
    "kind",
    "title",
    "summary",
    "link",
    "published_at",
    "fetched_at",
    "updated_at",
}


def insert_row(conn: psycopg.Connection, table: str, row: dict[str, Any]) -> None:
    values = []
    for key, value in row.items():
        if value is not None and key in TIMES:
            value = to_datetime(value)
        elif value is not None and key in JSONB:
            value = Jsonb(value)
        values.append(value)
    # threat_news.id는 GENERATED ALWAYS라 샘플의 고정 id를 넣으려면 OVERRIDING이 필요하다
    overriding = sql.SQL("OVERRIDING SYSTEM VALUE" if table == "threat_news" else "")
    conn.execute(
        sql.SQL("INSERT INTO {} ({}) {} VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, row)),
            overriding,
            sql.SQL(", ").join(sql.Placeholder() * len(row)),
        ),
        values,
    )


@pytest.fixture
def database(temp_database: str, monkeypatch: pytest.MonkeyPatch) -> str:
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as conn:
        for table in TABLES:
            for row in SEED[table]:
                insert_row(conn, table, row)
    monkeypatch.setenv("DATABASE_URL", temp_database)
    return temp_database


@pytest.fixture
def client(database: str) -> Iterator[TestClient]:
    with admin_client() as test_client:
        yield test_client


def ids(response: Any) -> list[Any]:
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


# GET /api/hunts


def test_hunt_list_is_newest_first_with_list_fields_only(client: TestClient) -> None:
    response = client.get("/api/hunts")
    assert ids(response) == [H5, H4, H3, H2, H1]
    body = response.json()
    assert body["next_cursor"] is None
    seed = {h["id"]: h for h in SEED["hunts"]}
    for item in body["items"]:
        assert set(item) == LIST_KEYS
        assert item == {key: seed[item["id"]][key] for key in LIST_KEYS}


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"status": "pending"}, [H1]),
        ({"status": "confirmed"}, [H2]),
        ({"status": "rejected"}, [H3]),
        ({"status": "inconclusive"}, [H4]),
        ({"status": "failed"}, [H5]),
        ({"hunt_run_id": HRN_A}, [H3, H2, H1]),
        ({"hunt_run_id": HRN_B}, [H5, H4]),
        ({"hunt_run_id": HRN_B, "status": "failed"}, [H5]),
        ({"hunt_run_id": HRN_A, "status": "failed"}, []),
        ({"hunt_run_id": new_id("hrn")}, []),
    ],
)
def test_hunt_list_filters(client: TestClient, params: dict[str, str], expected: list[str]) -> None:
    assert ids(client.get("/api/hunts", params=params)) == expected


def test_hunt_list_pages(client: TestClient) -> None:
    first = client.get("/api/hunts", params={"limit": 2})
    assert ids(first) == [H5, H4]
    assert first.json()["next_cursor"] == H4
    second = client.get("/api/hunts", params={"limit": 2, "cursor": H4})
    assert ids(second) == [H3, H2]
    assert second.json()["next_cursor"] == H2
    third = client.get("/api/hunts", params={"limit": 2, "cursor": H2})
    assert ids(third) == [H1]
    assert third.json()["next_cursor"] is None


def test_hunt_list_exact_page_has_no_next_cursor(client: TestClient) -> None:
    response = client.get("/api/hunts", params={"limit": 5})
    assert len(ids(response)) == 5
    assert response.json()["next_cursor"] is None


def test_hunt_list_cursor_with_filter(client: TestClient) -> None:
    response = client.get("/api/hunts", params={"hunt_run_id": HRN_A, "limit": 1, "cursor": H3})
    assert ids(response) == [H2]
    assert response.json()["next_cursor"] == H2


# GET /api/hunts/{hunt_id}


@pytest.mark.parametrize("index", range(5))
def test_hunt_detail_hunt_part_is_the_contract_record(client: TestClient, index: int) -> None:
    seed = SEED["hunts"][index]
    response = client.get(f"/api/hunts/{seed['id']}")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"hunt", "techniques", "ticket_id", "runs"}
    validate_contract("hunt", body["hunt"])
    assert body["hunt"] == seed


def test_only_confirmed_hunt_has_ticket_id(client: TestClient) -> None:
    for hunt_id in (H1, H2, H3, H4, H5):
        body = client.get(f"/api/hunts/{hunt_id}").json()
        assert body["ticket_id"] == (TICKET if hunt_id == H2 else None)


def test_technique_names_come_from_configured_version(client: TestClient) -> None:
    body = client.get(f"/api/hunts/{H2}").json()
    # T1059는 다른 버전(19.0)에만 있다
    assert body["techniques"] == [
        {"id": "T1190", "name": "Exploit Public-Facing Application"},
        {"id": "T1059", "name": None},
    ]


def run_ids_of(subject: str) -> list[str]:
    rows = [r for r in SEED["agent_logs"] if r["subject_id"] == subject]
    return sorted(
        {r["run_id"] for r in rows},
        key=lambda run: min(r["started_at"] for r in rows if r["run_id"] == run),
    )


def test_hunt_detail_runs_summarize_generation_and_verification(client: TestClient) -> None:
    response = client.get(f"/api/hunts/{H2}")
    runs = response.json()["runs"]
    generation, failed_attempt, ok_attempt = (*run_ids_of(HRN_A), *run_ids_of(H2))
    assert runs == [
        {
            "run_id": generation,
            "task": "l3_hypothesize",
            "attempt": 1,
            "outcome": "ok",
            "failure": None,
            "tokens_in": 1000,
            "tokens_out": 200,
            "started_at": T0 - 5000,
            "duration_ms": 3000,
        },
        {
            "run_id": failed_attempt,
            "task": "l3_verify",
            "attempt": 1,
            "outcome": "error",
            "failure": "format_error",
            "tokens_in": 220,
            "tokens_out": 80,
            "started_at": T0 + H,
            "duration_ms": 3500,
        },
        {
            # tool 줄만 실패한 run은 성공이다
            "run_id": ok_attempt,
            "task": "l3_verify",
            "attempt": 2,
            "outcome": "ok",
            "failure": None,
            "tokens_in": 500,
            "tokens_out": 150,
            "started_at": T0 + 2 * H - 9000,
            "duration_ms": 7000,
        },
    ]
    assert MARKER not in response.text


def test_run_without_tokens_has_null_tokens(client: TestClient) -> None:
    runs = client.get(f"/api/hunts/{H5}").json()["runs"]
    (generation,) = run_ids_of(HRN_B)
    (verification,) = run_ids_of(H5)
    assert [r["run_id"] for r in runs] == [generation, verification]
    assert runs[1] == {
        "run_id": verification,
        "task": "l3_verify",
        "attempt": 1,
        "outcome": "error",
        "failure": "provider_error",
        "tokens_in": None,
        "tokens_out": None,
        "started_at": T0 + D + H,
        "duration_ms": 60000,
    }


def test_hunt_detail_never_contains_agent_log_input_or_output(client: TestClient) -> None:
    for hunt_id in (H1, H2, H3, H4, H5):
        response = client.get(f"/api/hunts/{hunt_id}")
        assert MARKER not in response.text
        for run in response.json()["runs"]:
            assert "input" not in run
            assert "output" not in run


def test_hunt_without_verification_runs_shows_generation_run_only(client: TestClient) -> None:
    runs = client.get(f"/api/hunts/{H1}").json()["runs"]
    assert [r["run_id"] for r in runs] == run_ids_of(HRN_A)


def test_unknown_hunt_id_is_404(client: TestClient) -> None:
    response = client.get(f"/api/hunts/{new_id('hnt')}")
    assert response.status_code == 404
    assert response.json() == {"error": "not_found"}


def test_llm_strings_come_back_unchanged(client: TestClient) -> None:
    body = client.get(f"/api/hunts/{H3}").json()
    assert body["hunt"]["reason"] == "<script>alert(1)</script> 업로드 흔적 없음"


# GET /api/threat-news


def test_news_list_is_newest_first_by_published_or_fetched(client: TestClient) -> None:
    response = client.get("/api/threat-news")
    # 5와 1은 정렬 시각이 같아 id가 큰 5가 먼저다. 3은 published_at이 없어 fetched_at으로 정렬된다
    assert ids(response) == [5, 1, 3, 2, 4]
    body = response.json()
    assert body["next_cursor"] is None
    seed = {n["id"]: n for n in SEED["threat_news"]}
    for item in body["items"]:
        assert set(item) == NEWS_KEYS
        assert item == {key: seed[item["id"]][key] for key in NEWS_KEYS}


def test_news_strings_come_back_unchanged(client: TestClient) -> None:
    items = client.get("/api/threat-news").json()["items"]
    injected = next(item for item in items if item["id"] == 2)
    assert injected["title"] == SEED["threat_news"][1]["title"]
    assert injected["link"] == "javascript:alert(1)"


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"source": "boannews"}, [5, 1, 4]),
        ({"source": "cisa_kev"}, [3]),
        ({"source": "없는출처"}, []),
        # 양끝 포함. 3은 fetched_at(T0 - D - 12H)으로 기간에 들어간다
        ({"since": T0 - D - 12 * H}, [5, 1, 3]),
        ({"until": T0 - D - 12 * H}, [3, 2, 4]),
        ({"since": T0 - 2 * D, "until": T0 - D}, [5, 1, 3, 2]),
        ({"since": T0 - 2 * D, "until": T0 - D, "source": "boannews"}, [5, 1]),
        ({"since": T0, "until": T0}, []),
    ],
)
def test_news_filters(client: TestClient, params: dict[str, Any], expected: list[int]) -> None:
    assert ids(client.get("/api/threat-news", params=params)) == expected


def test_news_pages(client: TestClient) -> None:
    first = client.get("/api/threat-news", params={"limit": 2})
    assert ids(first) == [5, 1]
    cursor = first.json()["next_cursor"]
    assert cursor == f"{T0 - D}_1"
    second = client.get("/api/threat-news", params={"limit": 2, "cursor": cursor})
    assert ids(second) == [3, 2]
    third = client.get(
        "/api/threat-news", params={"limit": 2, "cursor": second.json()["next_cursor"]}
    )
    assert ids(third) == [4]
    assert third.json()["next_cursor"] is None


def test_news_pages_do_not_skip_rows_within_the_same_millisecond(
    database: str, client: TestClient
) -> None:
    # 수집(#221)은 fetched_at에 마이크로초까지 넣는다. 같은 밀리초 안의 두 행이 모두 나와야 한다
    base = to_datetime(T0 + 5 * D)
    with psycopg.connect(database, autocommit=True) as conn:
        # 샘플은 id를 OVERRIDING으로 넣어 일련번호가 1에 머물러 있다
        conn.execute("SELECT setval(pg_get_serial_sequence('threat_news', 'id'), 100)")
        for offset, ref in ((700, "a"), (400, "b")):
            conn.execute(
                "INSERT INTO threat_news (source, kind, source_ref, title, summary, link,"
                " published_at, fetched_at, updated_at)"
                " VALUES ('boannews', 'rss', %s, '같은 밀리초', '', NULL, NULL, %s, %s)",
                (ref, base + timedelta(microseconds=offset), base + timedelta(microseconds=offset)),
            )
    seen: list[int] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 1}
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get("/api/threat-news", params=params)
        seen += ids(response)
        cursor = response.json()["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 7
    assert len(set(seen)) == 7
    assert seen[2:] == [5, 1, 3, 2, 4]
    first = client.get("/api/threat-news", params={"limit": 1}).json()["items"][0]
    assert first["fetched_at"] == T0 + 5 * D


# DB 세션


def test_api_session_is_read_only(database: str) -> None:
    with api_db.connect(load_settings()) as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("DELETE FROM hunts")
    with psycopg.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM hunts").fetchone() == (5,)
