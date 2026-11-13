"""유사 사례 검색을 실제 Qdrant로 확인한다(#313, qdrant 마커).

메모리 모드(qdrant-client)로는 보지 못하는 것: 빈 payload point 저장, 없는 컬렉션 오류 해석,
서버 쪽 Cosine 점수. 테스트마다 고유한 purpose를 써서 컬렉션이 겹치지 않게 하고 끝나면 지운다.
PostgreSQL은 쓰지 않는다(read_many를 가짜로 바꾼다).
"""

import asyncio
import secrets
from collections.abc import Iterator

import pytest
from test_tools_similar_cases import (
    NAME,
    SETTINGS,
    FakeDb,
    FixedEmbedder,
    config,
    hits_db,
    pid,
    tid,
)
from tool_helpers import Caller, parse

from soc.similar.index import upsert_ticket
from soc.similar.runtime import SERVICE_NAME, SimilarService
from soc.store import StoreError, VectorStore, create_client
from soc.tools import default_registry
from soc.tools import similar_cases as module

pytestmark = pytest.mark.qdrant

VECTORS = {"sql injection": [1.0, 0.0, 0.0], "login attack": [0.8, 0.6, 0.0]}


@pytest.fixture
def real_store() -> Iterator[VectorStore]:
    try:
        client = create_client(SETTINGS.qdrant, timeout=10)
    except StoreError as error:
        pytest.fail(f"qdrant 테스트에는 QDRANT_URL이 필요하다: {error}", pytrace=False)
    store = VectorStore(
        f"ticket_verdicts_test_{secrets.token_hex(6)}",
        FixedEmbedder(VECTORS),
        SETTINGS,
        client=client,
    )
    try:
        yield store
    finally:
        store.drop_collection()
        client.close()


def run(store: VectorStore, arguments: dict, db: FakeDb) -> dict:
    module.read_many = db  # type: ignore[assignment]
    caller = Caller(
        default_registry(),
        config(),
        services={SERVICE_NAME: SimilarService(store._embedder, store)},  # noqa: SLF001
    )
    return parse(asyncio.run(caller(NAME, arguments)))


@pytest.fixture(autouse=True)
def restore_read_many() -> Iterator[None]:
    original = module.read_many
    yield
    module.read_many = original


def test_empty_payload_points_round_trip_and_rank_by_cosine(real_store: VectorStore) -> None:
    # 컬렉션이 없는 채로 첫 색인을 하면 만들고 다시 넣는다
    assert not real_store.exists()
    embedder = FixedEmbedder({"a": [1.0, 0.0, 0.0], "b": [0.6, 0.8, 0.0], "c": [0.0, 0.0, 1.0]})
    for n, text in ((1, "a"), (2, "b"), (3, "c")):
        upsert_ticket(tid(n), text, embedder, real_store)

    hits = real_store.search([1.0, 0.0, 0.0], top_k=5)

    assert [hit.point_id for hit in hits] == [pid(1), pid(2), pid(3)]
    assert [hit.payload for hit in hits] == [{}, {}, {}]
    assert hits[0].score == pytest.approx(1.0)
    assert hits[1].score == pytest.approx(0.6)


def test_tool_searches_the_real_collection_and_applies_min_score(real_store: VectorStore) -> None:
    embedder = FixedEmbedder({"a": [1.0, 0.0, 0.0], "b": [0.6, 0.8, 0.0], "c": [0.0, 0.0, 1.0]})
    for n, text in ((1, "a"), (2, "b"), (3, "c")):
        upsert_ticket(tid(n), text, embedder, real_store)

    body = run(real_store, {"query": "sql injection", "min_score": 0.5}, hits_db())

    # 3번(코사인 0)은 min_score에서 빠지고 1번(1.0)과 2번(0.6)이 순서대로 남는다
    assert [r["ticket_id"] for r in body["results"]] == [tid(1), tid(2)]
    assert [r["score"] for r in body["results"]] == pytest.approx([1.0, 0.6], abs=1e-4)


def test_missing_real_collection_is_no_index_not_an_error(real_store: VectorStore) -> None:
    assert not real_store.exists()

    body = run(real_store, {"query": "sql injection"}, FakeDb())

    assert (body["status"], body["reason"]) == ("no_data", "no_index")
