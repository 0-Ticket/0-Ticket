"""유사 사례 색인을 실제 PostgreSQL 샘플로 확인한다(#313, db 마커).

Qdrant는 qdrant-client의 메모리 모드와 가짜 임베더를 쓴다. 실제 Qdrant는 test_similar_qdrant.py.
"""

import json
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fake_embedder import FakeEmbedder
from psycopg import sql
from psycopg.types.json import Jsonb
from qdrant_client import QdrantClient

from soc.contracts import to_datetime
from soc.db.migrate import migrate
from soc.similar.index import PURPOSE, index_ticket, make_indexer, reindex, ticket_text
from soc.store import StoreError, VectorStore
from soc.store.config import EmbedderSettings, QdrantSettings, StoreSettings

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).parent / "fixtures" / "similar" / "cases.json"
SETTINGS = StoreSettings(
    qdrant=QdrantSettings(url_env="QDRANT_URL"),
    embedder=EmbedderSettings(
        model_id="BAAI/bge-m3", revision="5617a9f61b028005a4858fdac845db406aefb181"
    ),
)
TIME_FIELDS = {"fetched_at", "time", "created_at", "updated_at", "verified_at", "confirmed_at"}
JSON_FIELDS = {"entities", "assets", "triage", "ocsf", "verdict", "details"}


def tid(n: int) -> str:
    return f"tkt_01a19f93-1150-7000-8000-{n:012d}"


def insert(conn: psycopg.Connection, table: str, data: dict[str, Any]) -> None:
    values = []
    for name, value in data.items():
        if name in TIME_FIELDS and value is not None:
            value = to_datetime(value)
        elif name in JSON_FIELDS and value is not None:
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


def load_into(url: str) -> dict[str, Any]:
    migrate(url)
    sample = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with psycopg.connect(url) as conn:
        for table in ("raw_records", "alerts", "hunts", "tickets", "incidents", "cases"):
            for row in sample[table]:
                insert(conn, table, row)
    return sample


@pytest.fixture
def database(temp_database: str) -> str:
    load_into(temp_database)
    return temp_database


def make_store(name: str = PURPOSE) -> VectorStore:
    return VectorStore(name, FakeEmbedder(), SETTINGS, client=QdrantClient(":memory:"))


def point_ids(store: VectorStore) -> set[str]:
    hits = store.search(FakeEmbedder().embed("x"), top_k=50)
    return {hit.point_id for hit in hits}


def test_ticket_text_is_alert_titles_and_never_the_verdict_reason(database: str) -> None:
    with psycopg.connect(database) as conn:
        text = ticket_text(conn, tid(1))

    assert text == "SQL injection attempt on login form"


def test_ticket_text_uses_hunt_hypothesis_for_an_l3_ticket_without_alerts(database: str) -> None:
    with psycopg.connect(database) as conn:
        assert ticket_text(conn, tid(7)) == "Possible DNS beaconing to an example domain"


def test_ticket_without_a_verdict_or_missing_has_no_text(database: str) -> None:
    with psycopg.connect(database) as conn:
        assert ticket_text(conn, tid(4)) is None  # new
        assert ticket_text(conn, tid(8)) is None  # 실패해 held가 됨. 판정 없음
        assert ticket_text(conn, tid(99)) is None


def test_index_ticket_writes_an_empty_payload_point_and_creates_the_collection(
    database: str,
) -> None:
    store = make_store()
    assert not store.exists()

    with psycopg.connect(database) as conn:
        assert index_ticket(conn, tid(1), FakeEmbedder(), store) is True
        assert index_ticket(conn, tid(4), FakeEmbedder(), store) is False

    hits = store.search(FakeEmbedder().embed("SQL injection attempt on login form"), top_k=5)
    assert [(hit.point_id, hit.payload) for hit in hits] == [(tid(1).removeprefix("tkt_"), {})]
    assert hits[0].score == pytest.approx(1.0)


def test_reindex_indexes_every_ticket_with_a_verdict(database: str) -> None:
    store = make_store()

    counts = reindex(database, FakeEmbedder(), store)

    # 판정이 있는 Ticket 1, 2, 3, 5, 6, 7. 판정이 없는 4와 8은 대상이 아니다
    assert counts == {"processed": 6, "succeeded": 6, "skipped": 0, "failed": 0}
    assert point_ids(store) == {tid(n).removeprefix("tkt_") for n in (1, 2, 3, 5, 6, 7)}
    assert reindex(database, FakeEmbedder(), store)["succeeded"] == 6  # 다시 돌려도 같다


def test_reindex_recreate_drops_stale_points(database: str) -> None:
    store = make_store()
    reindex(database, FakeEmbedder(), store)
    store.upsert("01a19f93-1150-7000-8000-0000000000ff", FakeEmbedder().embed("old"), {})

    reindex(database, FakeEmbedder(), store, recreate=True)

    assert "01a19f93-1150-7000-8000-0000000000ff" not in point_ids(store)


def test_reindex_counts_a_failed_ticket_and_continues(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store()
    real = FakeEmbedder()

    class Flaky:
        dimension = real.dimension

        def embed(self, text: str) -> list[float]:
            if "Brute force" in text:
                raise ValueError("임베딩 실패")
            return real.embed(text)

    counts = reindex(database, Flaky(), store)

    assert counts["failed"] == 1
    assert counts["succeeded"] == 5


def test_indexer_swallows_store_failures_so_the_l1_verdict_stays(database: str) -> None:
    class Broken:
        def upsert(self, *_: object) -> None:
            raise StoreError("끊김")

    indexer = make_indexer(FakeEmbedder(), Broken())  # type: ignore[arg-type]

    with psycopg.connect(database) as conn:
        indexer(conn, tid(1))  # 예외 없이 끝난다
        status = conn.execute("SELECT status FROM tickets WHERE id = %s", (tid(1),)).fetchone()
    assert status == ("closed",)
