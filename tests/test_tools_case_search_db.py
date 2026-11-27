"""Case 검색 도구를 실제 PostgreSQL과 읽기 역할로 확인한다(#392, D-087, db 마커).

임시 DB에 마이그레이션(0312 포함)을 적용하고 tests/fixtures/case_search/cases.json의 샘플을 넣는다.
도구는 테스트가 만든 임시 LOGIN 역할(soc_agent_reader 멤버, 임의 비밀번호, 끝나면 삭제)로 접속한다.
Qdrant는 qdrant-client 메모리 모드와 가짜 임베더를 쓴다.
"""

import asyncio
import secrets
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from case_search_helpers import (
    NAME,
    QUERY,
    SAMPLE,
    SERVICE,
    VectorEmbedder,
    cid,
    config,
    make_service,
)
from conftest import HiddenUrl
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
from test_tools_case_search import body as fake_body
from tool_helpers import Caller, parse

from soc.contracts import to_datetime
from soc.db.migrate import migrate
from soc.tools import default_registry

pytestmark = pytest.mark.db

READER = "soc_agent_reader"
TIME_FIELDS = {
    "fetched_at",
    "time",
    "created_at",
    "updated_at",
    "verified_at",
    "confirmed_at",
    "resolved_at",
}
JSON_FIELDS = {
    "entities",
    "assets",
    "triage",
    "ocsf",
    "verdict",
    "details",
    "timeline",
    "techniques",
}
TABLES = (
    "raw_records",
    "alerts",
    "hunts",
    "tickets",
    "incidents",
    "incident_artifacts",
    "incident_proposals",
    "cases",
)


def insert(conn: psycopg.Connection, table: str, data: dict[str, Any]) -> None:
    values = []
    for name, value in data.items():
        if name in TIME_FIELDS and value is not None:
            value = to_datetime(value)
        elif (
            name in JSON_FIELDS
            and value is not None
            # verdict는 tickets에서는 jsonb이고 incident_artifacts에서는 text다(0200)
            and not (table == "incident_artifacts" and name == "verdict")
        ):
            value = Jsonb(value)
        values.append(value)
    conn.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, data)),
            sql.SQL(", ").join(sql.Placeholder() * len(data)),
        ),
        values,
    )


@pytest.fixture
def reader_url(temp_database: HiddenUrl, monkeypatch: pytest.MonkeyPatch) -> Iterator[HiddenUrl]:
    """soc_agent_reader 멤버인 임시 LOGIN 역할. 비밀번호는 임의 값이고 끝나면 역할을 지운다."""
    migrate(temp_database)
    with psycopg.connect(temp_database) as conn:
        for table in TABLES:
            for row in SAMPLE[table]:
                insert(conn, table, row)
    name = f"soc_test_reader_{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(16)
    with psycopg.connect(temp_database, autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE {}").format(
                sql.Identifier(name), sql.Literal(password), sql.Identifier(READER)
            )
        )
    url = HiddenUrl(make_conninfo(temp_database, user=name, password=password))
    monkeypatch.setenv("AGENT_DATABASE_URL", url)
    try:
        yield url
    finally:
        with psycopg.connect(temp_database, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))


def run_real(args: dict[str, Any], *, service: Any = None, cfg: dict | None = None) -> dict:
    caller = Caller(
        default_registry(),
        cfg or config(),
        stage="l3",
        services={SERVICE: service or make_service()},
    )
    return parse(asyncio.run(caller(NAME, args)))


# 읽기 역할(마이그레이션 0312)

GRANTED = [
    "SELECT id, incident_id, title, summary, severity, entities, confirmed_at, status FROM cases",
    "SELECT id, origin, title, created_at, alert_ids FROM tickets",
    "SELECT id, ticket_ids, status FROM incidents",
    "SELECT id, incident_id, analysis_round, verdict, timeline, techniques, impact, cause,"
    " further_risk, evidence_ids FROM incident_artifacts",
    "SELECT artifact_id, kind, seq, priority, title, detail, rationale FROM incident_proposals",
    "SELECT id, title, time, severity FROM alerts",
]


@pytest.mark.parametrize("statement", GRANTED)
def test_reader_reads_the_granted_columns(reader_url: HiddenUrl, statement: str) -> None:
    with psycopg.connect(reader_url) as conn:
        assert conn.execute(statement).fetchall()


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT confirmed_by FROM cases",
        "SELECT assignee FROM cases",
        "SELECT resolved_at FROM cases",
        "SELECT details FROM cases",
        "SELECT * FROM cases",
        "SELECT details FROM tickets",
        "SELECT hunt_id FROM tickets",
        "SELECT updated_at FROM tickets",
        "SELECT * FROM tickets",
        "SELECT title FROM incidents",
        "SELECT summary FROM incidents",
        "SELECT summary FROM incident_artifacts",
        "SELECT assessed_severity FROM incident_artifacts",
        "SELECT created_at FROM incident_artifacts",
        "SELECT * FROM incident_artifacts",
        "SELECT id FROM incident_proposals",
        "SELECT created_at FROM incident_proposals",
        "SELECT * FROM incident_proposals",
        "SELECT count(*) FROM incident_reviews",
        "SELECT count(*) FROM case_index_jobs",
        "SELECT count(*) FROM hunts",
        "UPDATE cases SET status = 'resolved'",
        "DELETE FROM incident_artifacts",
        "INSERT INTO incident_proposals (id) VALUES ('x')",
        "UPDATE tickets SET title = 'x'",
    ],
)
def test_reader_is_denied_the_other_columns_tables_and_writes(
    reader_url: HiddenUrl, statement: str
) -> None:
    with psycopg.connect(reader_url) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(statement)


# 도구

# 세 Case가 도구 한도(4000)에 함께 안 들어가므로 상한을 넓힌다(합쳐 약 4,900자)
THREE = {"min_score": 0.5, "result_max_chars": 8_000}


def test_the_real_tables_give_the_same_answer_as_the_sample_rows(reader_url: HiddenUrl) -> None:
    for args, section in (
        ({"query": QUERY, "limit": 3}, THREE),
        ({"query": QUERY, "limit": 3}, {**THREE, "list_max_items": 2}),
        ({"query": QUERY, "limit": 3}, {**THREE, "text_max_chars": 40}),  # 문장을 많이 자른다
    ):
        real = run_real(args, cfg=config(section=section))
        # fake_body가 read_many를 가짜로 바꾸므로 반복마다 되돌린다(다음 real이 진짜 표를 읽게)
        with pytest.MonkeyPatch.context() as patch:
            fake = fake_body(patch, args, cfg=config(section=section))
        assert real == fake
        assert real["returned"] == 3 and real["omitted"] == 0


def test_latest_artifact_and_its_recommendations_come_from_the_real_tables(
    reader_url: HiddenUrl,
) -> None:
    result = run_real({"query": QUERY, "limit": 3}, cfg=config(section=THREE))

    by_id = {r["case"]["id"]: r for r in result["results"]}
    first = by_id[cid(1)]
    assert first["artifact"]["analysis_round"] == 2
    assert "OLD-ROUND-ONE" not in str(result)
    assert [r["title"] for r in first["recommendations"]][-1] == "Remove the uploaded file"
    assert by_id[cid(2)]["artifact"] is None
    assert {t["origin"] for t in by_id[cid(3)]["tickets"]} == {"l3", "auto"}
    assert [a["id"][-1] for a in by_id[cid(3)]["alerts"]] == ["5"]


def test_long_case_lists_are_capped_in_sql_and_the_totals_come_from_the_tables(
    reader_url: HiddenUrl,
) -> None:
    service = make_service(
        embedder=VectorEmbedder({QUERY: [0.0, 0.6, 0.8]})
    )  # Case 5(극단)만 맞춘다

    result = run_real(
        {"query": QUERY, "limit": 1},
        service=service,
        cfg=config(section={"min_score": 0.99, "list_max_items": 4, "result_max_chars": 30_000}),
    )

    [only] = result["results"]
    assert (only["tickets_total"], len(only["tickets"])) == (12, 4)
    assert (only["alerts_total"], len(only["alerts"])) == (24, 4)
    # 알럿은 심각도 내림차순이라 가장 높은 것부터 보인다
    long_alerts = [a for a in SAMPLE["alerts"] if 300 <= int(a["id"][-12:]) < 400]  # Case 5의 알럿
    expected = sorted(long_alerts, key=lambda a: (-a["severity"], a["time"], a["id"]))[:4]
    assert [a["id"] for a in only["alerts"]] == [a["id"] for a in expected]


def test_a_review_reason_in_the_database_never_reaches_the_result(
    reader_url: HiddenUrl, temp_database: HiddenUrl
) -> None:
    with psycopg.connect(temp_database, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO incident_reviews (incident_id, decision, reason, decided_by, review_round,"
            " analysis_round) VALUES (%s, 'reject', 'REJECT-REASON-MARKER', 'analyst.kim', 1, 1)",
            ("inc_01a19f93-1392-7000-8000-000000000001",),
        )

    result = run_real({"query": QUERY, "limit": 3}, cfg=config(section=THREE))

    assert "REJECT-REASON-MARKER" not in str(result)
    assert "analyst.kim" not in str(result)


def test_a_point_without_a_case_row_is_dropped_against_the_real_tables(
    reader_url: HiddenUrl,
) -> None:
    from case_search_helpers import POINTS

    service = make_service({9: [1.0, 0.0, 0.0], **POINTS})

    result = run_real({"query": QUERY, "limit": 3}, service=service, cfg=config(section=THREE))

    assert [r["case"]["id"] for r in result["results"]] == [cid(1), cid(2), cid(3)]
    assert cid(9) not in str(result)
