"""Case 검색 도구를 실제 Qdrant로 확인한다(#392, D-087, qdrant·db 마커).

메모리 모드로는 보지 못하는 것: 승인으로 생긴 Case가 워커를 거쳐 실제 컬렉션에 들어가 검색되는
흐름과 없는 컬렉션 오류 해석. 테스트마다 고유한 purpose를 써서 컬렉션이 겹치지 않게 하고 끝나면
지운다. PostgreSQL 샘플과 읽기 역할은 test_tools_case_search_db.py와 같다.
"""

import asyncio
import secrets
from collections.abc import Iterator

import psycopg
import pytest
from case_search_helpers import NAME, SERVICE, SETTINGS, config
from conftest import HiddenUrl
from fake_embedder import FakeEmbedder
from psycopg.rows import dict_row
from test_tools_case_search_db import reader_url  # noqa: F401  (fixture)
from tool_helpers import Caller, parse

from soc.api import ui_write
from soc.case_index import index
from soc.case_index.runtime import ConfirmedCasesService
from soc.case_index.text import case_text
from soc.store import StoreError, VectorStore, create_client
from soc.tools import default_registry

pytestmark = [pytest.mark.db, pytest.mark.qdrant, pytest.mark.usefixtures("reader_url")]

INCIDENT = "inc_01a19f93-1392-7000-8000-000000000009"


@pytest.fixture
def real_store() -> Iterator[VectorStore]:
    try:
        client = create_client(SETTINGS.qdrant, timeout=10)
    except StoreError as error:
        pytest.fail(f"qdrant 테스트에는 QDRANT_URL이 필요하다: {error}", pytrace=False)
    store = VectorStore(
        f"confirmed_cases_test_{secrets.token_hex(6)}", FakeEmbedder(), SETTINGS, client=client
    )
    try:
        yield store
    finally:
        if store.exists():
            store.drop_collection()
        client.close()


def search(service: ConfirmedCasesService, query: str) -> dict:
    caller = Caller(
        default_registry(),
        config(section={"min_score": 0.99}),
        stage="l3",
        services={SERVICE: service},
    )
    return parse(asyncio.run(caller(NAME, {"query": query, "limit": 1})))


def test_an_approved_case_is_indexed_by_the_worker_and_found_by_the_tool(
    temp_database: HiddenUrl, real_store: VectorStore
) -> None:
    embedder = FakeEmbedder()
    with psycopg.connect(temp_database, row_factory=dict_row) as conn:
        conn.execute(
            "INSERT INTO incidents (id, title, summary, status, ticket_ids, entities, severity,"
            " assessed_severity, analysis_round, review_round, created_at, updated_at, details)"
            " VALUES (%s, 'Approved incident', 'Approved summary', 'awaiting_review',"
            " ARRAY['tkt_01a19f93-1392-7000-8000-000000000001'], '[]', 3, 3, 1, 0,"
            " now(), now(), '{}')",
            (INCIDENT,),
        )
        case_id = ui_write.approve_incident(conn, INCIDENT, "analyst.kim")["case_id"]
    index.CaseIndexWorker(str(temp_database), SETTINGS, embedder, real_store).handle(case_id)
    service = ConfirmedCasesService(embedder, real_store)

    result = search(service, case_text("Approved incident", "Approved summary", None))

    [only] = result["results"]
    assert only["case"]["id"] == case_id
    assert only["case"]["summary"] == "Approved summary"
    assert only["score"] == pytest.approx(1.0, abs=1e-3)
    assert only["artifact"] is None  # 이 샘플에는 Artifact가 없다


def test_the_tool_finds_the_indexed_sample_cases_by_cosine(
    temp_database: HiddenUrl, real_store: VectorStore
) -> None:
    embedder = FakeEmbedder()
    assert index.reindex(str(temp_database), embedder, real_store)["failed"] == 0
    service = ConfirmedCasesService(embedder, real_store)

    result = search(
        service,
        case_text(
            "Failed logins burst on example VPN",
            "Many failed logins from one address on the VPN",
            None,
        ),
    )

    [only] = result["results"]
    assert only["case"]["title"] == "Failed logins burst on example VPN"
    assert only["alerts"][0]["title"] == "Failed logins burst on example VPN"


def test_a_missing_collection_is_no_data_with_the_real_server(real_store: VectorStore) -> None:
    assert not real_store.exists()  # 만들지 않았다

    result = search(ConfirmedCasesService(FakeEmbedder(), real_store), "anything")

    assert (result["status"], result["reason"]) == ("no_data", "no_index")
