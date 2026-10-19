import json
from pathlib import Path

import pytest

from soc.config import load_config
from soc.contracts import validate_contract
from soc.l1.tickets import TicketNotDecidedError
from soc.store.vectors.base import VectorSearchHit
from soc.store.vectors.tickets import VectorTicketService, build_ticket_vector_doc

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/vectors"


def load_decided_tickets():
    return json.loads((FIXTURES / "decided_tickets.json").read_text(encoding="utf-8"))


def load_unresolved_ticket():
    return json.loads((FIXTURES / "not_decided_ticket.json").read_text(encoding="utf-8"))


class FakeEmbedder:
    def __init__(self):
        self.texts = []

    def embed(self, text):
        self.texts.append(text)
        return [0.1, 0.2, 0.3]


class FakeVectorStore:
    def __init__(self):
        self.documents = []
        self.keyword_queries = []
        self.vector_queries = []
        self.keyword_hits = []
        self.vector_hits = []

    def upsert(self, document, vector):
        self.documents.append((document, list(vector)))

    def search_by_keywords(self, keywords, *, limit):
        self.keyword_queries.append((tuple(keywords), limit))
        return self.keyword_hits[:limit]

    def search_by_vector(self, vector, *, limit):
        self.vector_queries.append((list(vector), limit))
        return self.vector_hits[:limit]

    def close(self):
        pass


def load_small_dimension_settings():
    settings = load_config(environ={})
    return settings.model_copy(
        update={"embedder": settings.embedder.model_copy(update={"dimensions": 3})}
    )


def test_ticket_doc_uses_c19_ticket_collection_and_exact_entity_keywords():
    ticket = load_decided_tickets()[0]

    document = build_ticket_vector_doc(ticket)

    assert validate_contract("VectorDoc", document).model_dump(mode="json") == document
    assert document["collection"] == "closed_tickets"
    assert document["source_kind"] == "ticket"
    assert document["source_id"] == ticket["ticket_id"]
    assert document["keywords"] == ["203.0.113.10", "web-01"]
    assert "The request was blocked" in document["text"]


def test_ticket_doc_id_is_stable_for_idempotent_seed_upserts():
    ticket = load_decided_tickets()[0]

    assert build_ticket_vector_doc(ticket)["doc_id"] == build_ticket_vector_doc(ticket)["doc_id"]


def test_ticket_sink_rejects_non_decided_ticket_before_embedding_or_storage():
    embedder = FakeEmbedder()
    store = FakeVectorStore()
    service = VectorTicketService(store, embedder, load_small_dimension_settings())

    with pytest.raises(TicketNotDecidedError):
        service.add_decided_ticket(load_unresolved_ticket())

    assert embedder.texts == []
    assert store.documents == []


@pytest.mark.parametrize("status", ["closed_benign", "closed_fp", "l2_escalated"])
def test_ticket_sink_indexes_only_final_decision_statuses(status):
    ticket = load_decided_tickets()[0] | {"status": status}
    embedder = FakeEmbedder()
    store = FakeVectorStore()
    service = VectorTicketService(store, embedder, load_small_dimension_settings())

    service.add_decided_ticket(ticket)

    document, vector = store.documents[0]
    assert document["source_id"] == ticket["ticket_id"]
    assert document["source_kind"] == "ticket"
    assert vector == [0.1, 0.2, 0.3]


def test_search_by_ticket_and_entities_sentence_uses_keyword_and_vector_candidates():
    settings = load_small_dimension_settings()
    embedder = FakeEmbedder()
    store = FakeVectorStore()
    store.keyword_hits = []
    store.vector_hits = []
    service = VectorTicketService(store, embedder, settings)
    ticket = load_decided_tickets()[0]

    assert service.search_by_ticket(ticket, k=3) == []
    assert (
        service.search_by_entities(ticket["entities"], "blocked SQL injection request", k=4) == []
    )

    assert store.keyword_queries == [
        (("203.0.113.10", "web-01"), 12),
        (("203.0.113.10", "web-01"), 16),
    ]
    assert store.vector_queries == [([0.1, 0.2, 0.3], 12), ([0.1, 0.2, 0.3], 16)]
    assert len(embedder.texts) == 2
    assert "blocked SQL injection request" in embedder.texts[1]


def test_search_returns_ticket_id_and_score_using_configured_fusion_method():
    settings = load_small_dimension_settings()
    embedder = FakeEmbedder()
    store = FakeVectorStore()
    store.keyword_hits = [VectorSearchHit("tk_z_exact", 1.0)]
    store.vector_hits = [VectorSearchHit("tk_a_semantic", 0.99)]
    service = VectorTicketService(store, embedder, settings)

    result = service.search_by_entities([{"type": "ip", "value": "203.0.113.10"}], "web scan", k=2)

    assert settings.vector_search.fusion_method == "rrf"
    assert [ticket_id for ticket_id, _ in result] == ["tk_a_semantic", "tk_z_exact"]


def test_vector_ticket_service_can_switch_fusion_function_from_config():
    settings = load_small_dimension_settings()
    settings = settings.model_copy(
        update={
            "vector_search": settings.vector_search.model_copy(
                update={"fusion_method": "keyword_first"}
            )
        }
    )
    store = FakeVectorStore()
    store.keyword_hits = [VectorSearchHit("tk_z_exact", 1.0)]
    store.vector_hits = [VectorSearchHit("tk_a_semantic", 0.99)]
    service = VectorTicketService(store, FakeEmbedder(), settings)

    results = service.search_by_entities([{"type": "ip", "value": "203.0.113.10"}], "web scan", k=2)

    assert [ticket_id for ticket_id, _ in results] == ["tk_z_exact", "tk_a_semantic"]
