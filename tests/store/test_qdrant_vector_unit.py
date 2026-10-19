import json
import warnings
from pathlib import Path

from qdrant_client import QdrantClient

from soc.store.vectors.qdrant import QdrantVectorStore
from soc.store.vectors.tickets import build_ticket_vector_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "vectors"


def test_qdrant_vector_store_works_without_a_qdrant_server():
    tickets = json.loads((FIXTURES / "decided_tickets.json").read_text(encoding="utf-8"))
    client = QdrantClient(":memory:")
    store = QdrantVectorStore(
        client,
        collection="closed_tickets",
        dimensions=3,
        owns_client=True,
    )
    vectors = ([1.0, 0.0, 0.0], [0.8, 0.2, 0.0], [0.0, 1.0, 0.0])

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message="Payload indexes have no effect in the local Qdrant"
            )
            store.ensure_collection()
        for ticket, vector in zip(tickets, vectors, strict=True):
            store.upsert(build_ticket_vector_doc(ticket), vector)

        semantic_hits = store.search_by_vector([1.0, 0.0, 0.0], limit=3)
        keyword_hits = store.search_by_keywords(["203.0.113.10", "web-01"], limit=3)

        assert semantic_hits[0].ticket_id == tickets[0]["ticket_id"]
        assert [hit.ticket_id for hit in keyword_hits] == [
            tickets[0]["ticket_id"],
            tickets[2]["ticket_id"],
        ]
        assert keyword_hits[0].matched_keywords == ("203.0.113.10", "web-01")
    finally:
        store.close()
