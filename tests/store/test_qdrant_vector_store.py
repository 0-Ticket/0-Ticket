import uuid

import pytest
from qdrant_client import QdrantClient

from soc.config import load_config
from soc.store.vectors.qdrant import QdrantVectorStore
from soc.store.vectors.tickets import build_ticket_vector_doc

pytestmark = pytest.mark.qdrant


def test_qdrant_indexes_decided_ticket_and_supports_exact_and_vector_search():
    settings = load_config(environ={})
    collection = f"closed_tickets_test_{uuid.uuid4().hex[:12]}"
    client = QdrantClient(url=settings.vector_store.url, timeout=5)
    store = QdrantVectorStore(client, collection=collection, dimensions=3)
    tickets = [
        {
            "ticket_id": "tk_qdrant_exact",
            "origin": "scenario",
            "status": "closed_fp",
            "handling_type": "web_attack",
            "specialist": "web",
            "priority": 5,
            "alert_ids": ["al_qdrant_exact"],
            "entities": [{"type": "ip", "value": "203.0.113.10"}],
            "verdict": {
                "verdict": "fp",
                "confidence": 0.9,
                "summary": "Synthetic exact query sample.",
                "evidence": [
                    {"ref_type": "raw", "ref_id": "raw_qdrant_exact", "note": "Synthetic"}
                ],
                "recommended_action": "No action.",
                "needs_human": False,
                "human_reason": None,
            },
            "extensions": {},
            "created_at": 1791849600000,
            "updated_at": 1791849600000,
            "awaiting_human_at": None,
        },
        {
            "ticket_id": "tk_qdrant_semantic",
            "origin": "scenario",
            "status": "closed_benign",
            "handling_type": "scan",
            "specialist": "web",
            "priority": 3,
            "alert_ids": ["al_qdrant_semantic"],
            "entities": [{"type": "host", "value": "web-01"}],
            "verdict": {
                "verdict": "tp",
                "confidence": 0.8,
                "summary": "A synthetic scan was blocked.",
                "evidence": [
                    {"ref_type": "raw", "ref_id": "raw_qdrant_semantic", "note": "Synthetic"}
                ],
                "recommended_action": "No action.",
                "needs_human": False,
                "human_reason": None,
            },
            "extensions": {},
            "created_at": 1791849601000,
            "updated_at": 1791849601000,
            "awaiting_human_at": None,
        },
    ]

    try:
        store.ensure_collection()
        for ticket, vector in zip(tickets, ([1.0, 0.0, 0.0], [0.8, 0.2, 0.0]), strict=True):
            document = build_ticket_vector_doc(ticket)
            store.upsert(document, vector)

        vector_hits = store.search_by_vector([1.0, 0.0, 0.0], limit=2)
        keyword_hits = store.search_by_keywords(["203.0.113.10"], limit=2)

        assert [hit.ticket_id for hit in vector_hits] == [
            "tk_qdrant_exact",
            "tk_qdrant_semantic",
        ]
        assert [hit.ticket_id for hit in keyword_hits] == ["tk_qdrant_exact"]
        assert keyword_hits[0].matched_keywords == ("203.0.113.10",)
    finally:
        if client.collection_exists(collection):
            client.delete_collection(collection)
        store.close()
        client.close()
