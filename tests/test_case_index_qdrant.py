"""승인된 Case 색인을 실제 Qdrant로 확인한다(#391, D-084, qdrant·db 마커).

메모리 모드로는 보지 못하는 것: 빈 payload point 저장과 서버 쪽 Cosine 점수, 없는 컬렉션 오류 해석,
컬렉션 재생성. 테스트마다 고유한 purpose를 써서 컬렉션이 겹치지 않게 하고 끝나면 지운다.
PostgreSQL 샘플은 test_case_index_db.py와 같다.
"""

import secrets
from collections.abc import Iterator

import psycopg
import pytest
from fake_embedder import FakeEmbedder
from psycopg.rows import dict_row
from test_case_index_db import CASE, INC, SETTINGS, load_sample, run_index

from soc.api import ui_write
from soc.case_index import index
from soc.case_index.outbox import enqueue
from soc.case_index.source import point_id
from soc.db.migrate import migrate
from soc.store import StoreError, VectorStore, create_client

pytestmark = [pytest.mark.db, pytest.mark.qdrant]


@pytest.fixture
def database(temp_database: str) -> str:
    migrate(temp_database)
    load_sample(temp_database)
    return temp_database


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
        store.drop_collection()
        client.close()


def test_points_have_an_empty_payload_and_rank_by_cosine(
    database: str, real_store: VectorStore
) -> None:
    assert index.reindex(database, FakeEmbedder(), real_store, recreate=True) == {
        "processed": 3,
        "succeeded": 3,
        "failed": 0,
    }
    query = "title: Suspicious login burst"  # Case 2의 색인 텍스트(Artifact 없음)

    hits = real_store.search(FakeEmbedder().embed(query), top_k=5)

    assert len(hits) == 3
    assert (hits[0].point_id, hits[0].payload) == (point_id(CASE["2"]), {})
    assert hits[0].score == pytest.approx(1.0)
    assert all(hit.payload == {} for hit in hits)


def test_check_and_reindex_recover_a_lost_point_and_a_recreated_collection(
    database: str, real_store: VectorStore
) -> None:
    index.reindex(database, FakeEmbedder(), real_store, recreate=True)
    assert index.check(database, real_store) == {
        "cases": 3, "missing": 0, "no_job": 0, "pending": 0, "no_artifact": 1,
    }  # fmt: skip

    real_store.drop_collection()
    assert index.check(database, real_store)["missing"] == 3

    assert index.reindex(database, FakeEmbedder(), real_store)["failed"] == 0
    assert index.check(database, real_store)["missing"] == 0


def test_a_missing_collection_is_created_by_the_first_write(
    database: str, real_store: VectorStore
) -> None:
    with psycopg.connect(database, autocommit=True) as conn:
        enqueue(conn, CASE["1"])
    assert not real_store.exists()

    assert run_index(database, CASE["1"], FakeEmbedder(), real_store) is True

    assert real_store.exists()


def test_an_approved_case_is_found_after_the_worker_runs(
    database: str, real_store: VectorStore
) -> None:
    with psycopg.connect(database, row_factory=dict_row, autocommit=True) as conn:
        case_id = ui_write.approve_incident(conn, INC["4"], "tester")["case_id"]
    worker = index.CaseIndexWorker(database, SETTINGS, embedder=FakeEmbedder(), store=real_store)

    for pending in worker.poll(10):
        worker.handle(pending)

    ids = {hit.point_id for hit in real_store.search(FakeEmbedder().embed("x"), top_k=10)}
    assert point_id(case_id) in ids
