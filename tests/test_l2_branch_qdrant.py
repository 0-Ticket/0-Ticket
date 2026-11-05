"""L2 Ticket point 모양을 실제 Qdrant 왕복으로 확인한다."""

import secrets
from collections.abc import Iterator

import pytest
from fake_embedder import FakeEmbedder

from soc.store import StoreError, VectorStore, create_client
from soc.store.config import EmbedderSettings, QdrantSettings, StoreSettings

SETTINGS = StoreSettings(
    qdrant=QdrantSettings(url_env="QDRANT_URL"),
    embedder=EmbedderSettings(
        model_id="BAAI/bge-m3",
        revision="5617a9f61b028005a4858fdac845db406aefb181",
    ),
)


@pytest.fixture
def l2_store() -> Iterator[VectorStore]:
    try:
        client = create_client(SETTINGS.qdrant, timeout=10)
    except StoreError as error:
        pytest.fail(f"qdrant 테스트에는 QDRANT_URL이 필요하다: {error}", pytrace=False)
    store = VectorStore(
        f"ticket_branch_test_{secrets.token_hex(6)}",
        FakeEmbedder(),
        SETTINGS,
        client=client,
    )
    store.ensure_collection()
    try:
        yield store
    finally:
        store.drop_collection()
        client.close()


@pytest.mark.qdrant
def test_ticket_point_round_trip_and_closed_incident_cleanup(l2_store: VectorStore) -> None:
    embedder = FakeEmbedder()
    point_id = "01a19f93-1150-7000-8000-000000000101"
    incident_id = "inc_01a19f93-1150-7000-8000-000000000101"
    vector = embedder.embed("인공 Ticket")

    l2_store.upsert(point_id, vector, {"incident_id": incident_id})

    found = l2_store.search(vector, top_k=5)
    assert [(hit.point_id, hit.payload) for hit in found] == [
        (point_id, {"incident_id": incident_id})
    ]

    l2_store.delete_by_payload("incident_id", incident_id)
    assert l2_store.search(vector, top_k=5) == ()
