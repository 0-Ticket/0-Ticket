"""유사 사례 검색 도구를 실제 PostgreSQL과 읽기 역할로 확인한다(#313, db 마커).

임시 DB에 마이그레이션을 적용하고 tests/fixtures/similar/cases.json의 손으로 만든 샘플을 넣는다.
도구는 테스트가 만든 임시 LOGIN 역할(soc_agent_reader 멤버, 임의 비밀번호, 끝나면 삭제)로 접속한다.
Qdrant는 qdrant-client 메모리 모드와 가짜 임베더를 쓴다.
"""

import asyncio
import secrets
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from conftest import HiddenUrl
from fake_embedder import FakeEmbedder
from psycopg import sql
from psycopg.conninfo import make_conninfo
from qdrant_client import QdrantClient
from test_agent_core import CONFIG
from test_similar_db import SETTINGS, load_into, tid
from tool_helpers import Caller, parse

from soc.similar.index import reindex
from soc.similar.runtime import SERVICE_NAME, SimilarService
from soc.store import VectorStore
from soc.tools import default_registry

pytestmark = pytest.mark.db

READER = "soc_agent_reader"
NAME = "search_similar_cases"
SIMILAR = {
    "limit_default": 5,
    "limit_max": 10,
    "min_score": 0.5,
    "query_max_chars": 200,
    "reason_max_chars": 300,
    "entities_max": 5,
}
TITLES = {
    1: "SQL injection attempt on login form",
    2: "SQL injection attempt on search form",
    3: "Brute force SSH login from external host",
    5: "Port scan from external host",
    6: "Port scan from external host again",
    7: "Possible DNS beaconing to an example domain",
}


@pytest.fixture
def reader_url(temp_database: HiddenUrl, monkeypatch: pytest.MonkeyPatch) -> Iterator[HiddenUrl]:
    """soc_agent_reader 멤버인 임시 LOGIN 역할. 비밀번호는 임의 값이고 끝나면 역할을 지운다."""
    load_into(temp_database)
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


class PositiveEmbedder(FakeEmbedder):
    """모든 성분이 양수라 코사인이 0 아래로 내려가지 않는다. min_score는 0 이상만 받는다."""

    def embed(self, text: str) -> list[float]:
        values = [abs(v) + 0.01 for v in super().embed(text)]
        norm = sum(v * v for v in values) ** 0.5
        return [v / norm for v in values]


@pytest.fixture
def service(temp_database: HiddenUrl, reader_url: HiddenUrl) -> SimilarService:
    embedder = PositiveEmbedder()
    store = VectorStore("ticket_verdicts", embedder, SETTINGS, client=QdrantClient(":memory:"))
    reindex(temp_database, embedder, store)
    return SimilarService(embedder, store)


def run_tool(service: SimilarService, arguments: dict[str, Any], stage: str = "l1") -> dict:
    tools = {**CONFIG["tools"], "allowed": {"l1": [NAME], "l2": [NAME]}, "similar_cases": SIMILAR}
    caller = Caller(
        default_registry(),
        {**CONFIG, "tools": tools},
        stage=stage,
        services={SERVICE_NAME: service},
    )
    return parse(asyncio.run(caller(NAME, arguments)))


# 읽기 역할(마이그레이션 0007)


def test_reader_reads_only_the_granted_columns(reader_url: str) -> None:
    with psycopg.connect(reader_url) as conn:
        assert conn.execute(
            "SELECT id, status, verdict, entities, alert_ids, created_at FROM tickets"
        )
        assert conn.execute("SELECT id, ticket_ids, status FROM incidents").fetchall()
        assert conn.execute("SELECT id, incident_id FROM cases").fetchall() == [
            ("cas_01a19f93-1150-7000-8000-000000000001", "inc_01a19f93-1150-7000-8000-000000000001")
        ]


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT details FROM tickets",
        "SELECT * FROM tickets",
        "SELECT origin FROM tickets",
        "SELECT hunt_id FROM tickets",
        "SELECT title FROM incidents",
        "SELECT summary FROM incidents",
        "SELECT * FROM incidents",
        "SELECT confirmed_by FROM cases",
        "SELECT * FROM cases",
        "SELECT count(*) FROM hunts",
        "SELECT count(*) FROM agent_logs",
        "UPDATE tickets SET status = 'closed'",
        "DELETE FROM tickets",
        "UPDATE incidents SET status = 'dismissed'",
        "INSERT INTO cases (id) VALUES ('x')",
    ],
)
def test_reader_is_denied_other_columns_tables_and_writes(reader_url: str, statement: str) -> None:
    with psycopg.connect(reader_url) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(statement)


# 도구


def test_query_search_returns_decided_by_and_case_id_from_the_real_tables(
    service: SimilarService,
) -> None:
    human = run_tool(service, {"query": TITLES[2], "min_score": 0.99})
    agent = run_tool(service, {"query": TITLES[1], "min_score": 0.99})
    dismissed = run_tool(service, {"query": TITLES[6], "min_score": 0.99})

    [first] = human["results"]
    assert first["ticket_id"] == tid(2)
    assert (first["decided_by"], first["case_id"]) == (
        "human",
        "cas_01a19f93-1150-7000-8000-000000000001",
    )
    assert (first["status"], first["decision"]) == ("linked", "malicious")
    [second] = agent["results"]
    assert (second["ticket_id"], second["decided_by"], second["case_id"]) == (tid(1), "agent", None)
    assert (second["status"], second["decision"]) == ("closed", "benign")
    # 사람이 닫은 Incident(dismissed)도 Case가 없으면 agent다
    [third] = dismissed["results"]
    assert (third["ticket_id"], third["decided_by"], third["status"]) == (tid(6), "agent", "held")


def test_ticket_id_search_drops_itself_and_the_other_tickets_of_its_incident(
    service: SimilarService,
) -> None:
    # 5번 Ticket은 Incident 1(2번과 같은 Incident)에 속한다
    body = run_tool(service, {"ticket_id": tid(5), "min_score": 0, "limit": 10})

    ids = {r["ticket_id"] for r in body["results"]}
    assert tid(5) not in ids and tid(2) not in ids
    assert ids == {tid(1), tid(3), tid(6), tid(7)}
    assert body["searched"] == "ticket"


def test_ticket_id_search_works_for_a_ticket_without_a_verdict_yet(service: SimilarService) -> None:
    # 4번은 판정 전(new)이라 색인에 없지만 Alert 제목으로 찾을 수 있다
    body = run_tool(service, {"ticket_id": tid(4), "min_score": 0.0, "limit": 10})

    assert body["status"] == "ok"
    assert tid(4) not in {r["ticket_id"] for r in body["results"]}
    assert len(body["results"]) == 6  # 판정이 있는 Ticket 전부


def test_l3_ticket_without_alerts_and_unknown_ticket_are_no_data(service: SimilarService) -> None:
    l3 = run_tool(service, {"ticket_id": tid(7)})
    unknown = run_tool(service, {"ticket_id": tid(99)})

    assert (l3["status"], l3["reason"]) == ("no_data", "no_text")
    assert (unknown["status"], unknown["reason"]) == ("no_data", "ticket_not_found")


def test_no_match_is_an_empty_list_and_works_for_l2_too(service: SimilarService) -> None:
    body = run_tool(service, {"query": "completely unrelated sentence", "min_score": 1.0}, "l2")

    assert body["status"] == "ok" and body["results"] == [] and body["reason"] == "no_match"


def test_qdrant_point_without_a_database_row_is_dropped(
    temp_database: HiddenUrl, service: SimilarService
) -> None:
    ghost = "01a19f93-1150-7000-8000-0000000000ee"
    service.store.upsert(ghost, PositiveEmbedder().embed("ghost ticket"), {})

    body = run_tool(service, {"query": "ghost ticket", "min_score": 0.99})

    assert body["results"] == []
