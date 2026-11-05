"""Qdrant 벡터 저장소(#257).

실제 Qdrant가 필요한 테스트는 qdrant 마커로 나눈다. 기본 pytest에서 빠지고
`uv run pytest -m qdrant`로 돈다. 테스트마다 고유한 purpose를 써서 컬렉션이 겹치지 않게 하고,
성공·실패와 상관없이 자기가 만든 컬렉션만 지운다.
"""

import json
import secrets
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest
from fake_embedder import FakeEmbedder
from qdrant_client import models

from soc.store.config import EmbedderSettings, QdrantSettings, StoreSettings
from soc.store.qdrant import (
    CollectionMismatch,
    CollectionMissing,
    StoreError,
    VectorStore,
    build_filter,
    create_client,
)

FIXTURE = Path(__file__).parent / "fixtures" / "store" / "points.json"
SETTINGS = StoreSettings(
    qdrant=QdrantSettings(url_env="QDRANT_URL"),
    embedder=EmbedderSettings(
        model_id="BAAI/bge-m3", revision="5617a9f61b028005a4858fdac845db406aefb181"
    ),
)


def load_points() -> list[dict[str, Any]]:
    """손으로 만든 샘플 point를 읽는다."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["points"]


# --- 기본 pytest: 필터 변환과 입력 검증 ---


def test_build_filter_makes_and_of_equality_conditions() -> None:
    condition = build_filter({"group": "brute_force", "rank": 2, "linked": True})

    assert condition.must is not None
    assert [(c.key, c.match.value) for c in condition.must] == [
        ("group", "brute_force"),
        ("rank", 2),
        ("linked", True),
    ]


@pytest.mark.parametrize(
    "filters",
    [
        pytest.param({}, id="빈 표"),
        pytest.param({"": "x"}, id="빈 키"),
        pytest.param({"score": 0.5}, id="실수 값"),
        pytest.param({"group": None}, id="None 값"),
        pytest.param({"group": ["a", "b"]}, id="목록 값"),
        pytest.param({"group": {"a": 1}}, id="표 값"),
    ],
)
def test_build_filter_rejects_bad_input(filters: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        build_filter(filters)


def test_store_needs_no_client_to_derive_name() -> None:
    """이름은 설정에서만 나온다. 접속 없이도 같은 이름이 나온다."""
    store = VectorStore("l2_tickets", FakeEmbedder(), SETTINGS, client=_UnusedClient())

    assert store.collection.startswith("l2_tickets__bge-m3__")


class _UnusedClient:
    """부르면 테스트가 실패하는 가짜 클라이언트. 접속 없이 이름만 볼 때 쓴다."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"접속 없이 {name}을 불렀다")


# --- qdrant 마커: 실제 Qdrant ---


@pytest.fixture
def qdrant_client() -> Iterator[Any]:
    """QDRANT_URL의 Qdrant 클라이언트. 환경변수가 없으면 건너뛰지 않고 실패한다."""
    try:
        client = create_client(SETTINGS.qdrant, timeout=10)
    except StoreError as error:
        pytest.fail(f"qdrant 테스트에는 환경변수 QDRANT_URL이 필요하다: {error}", pytrace=False)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def purpose() -> str:
    """이 테스트만 쓰는 용도 이름. 컬렉션이 다른 테스트와 겹치지 않게 한다."""
    return f"test_{secrets.token_hex(6)}"


@pytest.fixture
def store(qdrant_client: Any, purpose: str) -> Iterator[VectorStore]:
    """빈 컬렉션이 준비된 저장소. 테스트가 성공하든 실패하든 그 컬렉션만 지운다."""
    store = VectorStore(purpose, FakeEmbedder(), SETTINGS, client=qdrant_client)
    store.ensure_collection()
    try:
        yield store
    finally:
        store.drop_collection()


@pytest.fixture
def bare_store(qdrant_client: Any, purpose: str) -> Iterator[VectorStore]:
    """컬렉션을 만들지 않은 저장소. 테스트가 만들었다면 끝에 지운다."""
    store = VectorStore(purpose, FakeEmbedder(), SETTINGS, client=qdrant_client)
    try:
        yield store
    finally:
        store.drop_collection()


@pytest.mark.qdrant
def test_ensure_collection_creates_with_embedder_dimension_and_cosine(
    bare_store: VectorStore, qdrant_client: Any
) -> None:
    assert bare_store.exists() is False

    bare_store.ensure_collection()

    assert bare_store.exists() is True
    vectors = qdrant_client.get_collection(bare_store.collection).config.params.vectors
    assert (vectors.size, vectors.distance) == (FakeEmbedder().dimension, models.Distance.COSINE)


@pytest.mark.qdrant
def test_ensure_collection_is_repeatable(store: VectorStore) -> None:
    """같은 설정으로 다시 불러도 오류가 없고 들어 있는 point가 그대로다."""
    point = load_points()[0]
    store.upsert(point["id"], FakeEmbedder().embed(point["text"]), point["payload"])

    store.ensure_collection()

    found = store.search(FakeEmbedder().embed(point["text"]), top_k=1)
    assert [hit.point_id for hit in found] == [point["id"]]


@pytest.mark.qdrant
def test_upsert_then_search_returns_id_score_and_payload(store: VectorStore) -> None:
    embedder = FakeEmbedder()
    points = load_points()
    for point in points:
        store.upsert(point["id"], embedder.embed(point["text"]), point["payload"])

    found = store.search(embedder.embed(points[0]["text"]), top_k=len(points))

    assert len(found) == len(points)
    assert found[0].point_id == points[0]["id"]
    assert found[0].payload == points[0]["payload"]
    # 같은 벡터라 Cosine 점수는 1에 가깝고, 결과는 점수가 높은 순서다
    assert found[0].score == pytest.approx(1.0, abs=1e-5)
    assert [hit.score for hit in found] == sorted((hit.score for hit in found), reverse=True)


@pytest.mark.qdrant
def test_upsert_overwrites_the_same_point_id(store: VectorStore) -> None:
    embedder = FakeEmbedder()
    point = load_points()[0]
    store.upsert(point["id"], embedder.embed(point["text"]), point["payload"])

    store.upsert(point["id"], embedder.embed(point["text"]), {"group": "다시 저장"})

    found = store.search(embedder.embed(point["text"]), top_k=5)
    assert len(found) == 1
    assert found[0].payload == {"group": "다시 저장"}


@pytest.mark.qdrant
def test_search_filters_payload_with_and(store: VectorStore) -> None:
    embedder = FakeEmbedder()
    points = load_points()
    for point in points:
        store.upsert(point["id"], embedder.embed(point["text"]), point["payload"])
    query = embedder.embed(points[0]["text"])

    both = store.search(query, top_k=5, filters={"group": "brute_force", "severity": "low"})
    one = store.search(query, top_k=5, filters={"group": "brute_force"})
    none = store.search(query, top_k=5, filters={"group": "brute_force", "severity": "none"})

    assert [hit.point_id for hit in both] == [points[1]["id"]]
    assert {hit.point_id for hit in one} == {points[0]["id"], points[1]["id"]}
    assert none == ()


@pytest.mark.qdrant
def test_search_filters_on_integer_and_boolean(store: VectorStore) -> None:
    embedder = FakeEmbedder()
    points = load_points()
    for point in points:
        store.upsert(point["id"], embedder.embed(point["text"]), point["payload"])
    query = embedder.embed(points[0]["text"])

    by_rank = store.search(query, top_k=5, filters={"rank": 3})
    by_flag = store.search(query, top_k=5, filters={"linked": False})

    assert [hit.point_id for hit in by_rank] == [points[2]["id"]]
    assert [hit.point_id for hit in by_flag] == [points[2]["id"]]


@pytest.mark.qdrant
def test_search_respects_top_k(store: VectorStore) -> None:
    embedder = FakeEmbedder()
    points = load_points()
    for point in points:
        store.upsert(point["id"], embedder.embed(point["text"]), point["payload"])

    assert len(store.search(embedder.embed(points[0]["text"]), top_k=2)) == 2


@pytest.mark.qdrant
def test_delete_by_payload_removes_every_matching_point(store: VectorStore) -> None:
    embedder = FakeEmbedder()
    points = load_points()
    for point in points:
        store.upsert(point["id"], embedder.embed(point["text"]), point["payload"])

    store.delete_by_payload("group", "brute_force")

    left = store.search(embedder.embed(points[0]["text"]), top_k=5)
    assert [hit.point_id for hit in left] == [points[2]["id"]]


@pytest.mark.qdrant
def test_drop_collection_then_create_again(bare_store: VectorStore) -> None:
    embedder = FakeEmbedder()
    point = load_points()[0]
    bare_store.ensure_collection()
    bare_store.upsert(point["id"], embedder.embed(point["text"]), point["payload"])

    bare_store.drop_collection()

    assert bare_store.exists() is False
    bare_store.ensure_collection()
    assert bare_store.exists() is True
    # 지웠다 만든 컬렉션은 비어 있다
    assert bare_store.search(embedder.embed(point["text"]), top_k=5) == ()


@pytest.mark.qdrant
@pytest.mark.parametrize(
    "existing",
    [
        pytest.param(
            models.VectorParams(size=FakeEmbedder().dimension + 1, distance=models.Distance.COSINE),
            id="다른 차원",
        ),
        pytest.param(
            models.VectorParams(size=FakeEmbedder().dimension, distance=models.Distance.DOT),
            id="다른 거리 방식",
        ),
        pytest.param(
            {
                "text": models.VectorParams(
                    size=FakeEmbedder().dimension, distance=models.Distance.COSINE
                )
            },
            id="이름 있는 vector",
        ),
    ],
)
def test_ensure_collection_rejects_different_collection(
    bare_store: VectorStore, qdrant_client: Any, existing: Any
) -> None:
    qdrant_client.create_collection(bare_store.collection, vectors_config=existing)

    with pytest.raises(CollectionMismatch):
        bare_store.ensure_collection()


@pytest.mark.qdrant
@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda store: store.search(FakeEmbedder().embed("가"), top_k=1), id="search"),
        pytest.param(
            lambda store: store.upsert(
                "0b4a1f6e-8c21-4b7a-9f10-3d5c6e7a8b90", FakeEmbedder().embed("가"), {}
            ),
            id="upsert",
        ),
        pytest.param(lambda store: store.delete_by_payload("group", "x"), id="delete"),
    ],
)
def test_missing_collection_raises_collection_missing(bare_store: VectorStore, call: Any) -> None:
    assert bare_store.exists() is False

    with pytest.raises(CollectionMissing):
        call(bare_store)


@pytest.mark.qdrant
def test_unreachable_qdrant_raises_store_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """접속 실패는 CollectionMissing이 아니라 StoreError다."""
    monkeypatch.setenv("QDRANT_URL", "http://127.0.0.1:6399")
    store = VectorStore(
        "test_unreachable",
        FakeEmbedder(),
        SETTINGS,
        client=create_client(SETTINGS.qdrant, timeout=2),
    )

    with pytest.raises(StoreError) as caught:
        store.exists()

    assert not isinstance(caught.value, CollectionMissing)


@pytest.mark.qdrant
def test_unique_purpose_isolates_collections(qdrant_client: Any, store: VectorStore) -> None:
    """고유한 purpose를 쓰면 다른 테스트의 컬렉션과 섞이지 않는다."""
    embedder = FakeEmbedder()
    point = load_points()[0]
    store.upsert(point["id"], embedder.embed(point["text"]), point["payload"])
    other = VectorStore(f"test_{secrets.token_hex(6)}", embedder, SETTINGS, client=qdrant_client)
    other.ensure_collection()

    try:
        assert other.collection != store.collection
        assert other.search(embedder.embed(point["text"]), top_k=5) == ()
    finally:
        other.drop_collection()

    # 남의 컬렉션은 지우지 않는다
    assert qdrant_client.collection_exists(store.collection) is True


@pytest.mark.qdrant
def test_cleanup_runs_even_when_the_body_fails(qdrant_client: Any, purpose: str) -> None:
    """store fixture와 같은 모양으로, 본문이 실패해도 자기 컬렉션만 지운다."""
    store = VectorStore(purpose, FakeEmbedder(), SETTINGS, client=qdrant_client)
    store.ensure_collection()
    name = store.collection

    with suppress(AssertionError):
        try:
            raise AssertionError("일부러 낸 실패")
        finally:
            store.drop_collection()

    assert qdrant_client.collection_exists(name) is False


@pytest.mark.qdrant
@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(lambda store: store.upsert("id", [0.1], {}), id="짧은 벡터 upsert"),
        pytest.param(lambda store: store.search([0.1], top_k=1), id="짧은 벡터 search"),
        pytest.param(lambda store: store.search(FakeEmbedder().embed("가"), top_k=0), id="top_k 0"),
    ],
)
def test_wrong_arguments_raise_value_error(store: VectorStore, bad: Any) -> None:
    with pytest.raises(ValueError):
        bad(store)
