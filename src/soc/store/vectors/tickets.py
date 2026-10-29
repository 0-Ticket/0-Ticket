"""Ticket C6 to C19 document building, indexing, and similarity search."""

import math
import uuid
from collections.abc import Mapping, Sequence
from importlib.resources import files
from typing import Any

from soc.config import Settings
from soc.contracts import validate_contract
from soc.l1.tickets import DECIDED_TICKET_STATUSES, TicketNotDecidedError
from soc.plugins import PluginRegistry
from soc.store.embedders import Embedder, open_embedder
from soc.store.vectors import VectorStore, open_vector_store

from .fusion import fuse_search_results

_DECIDED_TICKET_TEMPLATE = files("soc.store.vectors.templates").joinpath("decided_ticket.txt")
_ENTITY_SENTENCE_TEMPLATE = files("soc.store.vectors.templates").joinpath("entity_sentence.txt")
_CANDIDATE_MULTIPLIER = 4


def _validate_ticket(ticket: Mapping[str, Any]) -> dict[str, Any]:
    return validate_contract("Ticket", dict(ticket)).model_dump(mode="json")


def _validated_entities(entities: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    return [
        validate_contract("Entity", dict(entity)).model_dump(mode="json") for entity in entities
    ]


def _entity_values(entities: Sequence[Mapping[str, Any]]) -> list[str]:
    return list(dict.fromkeys(entity["value"] for entity in entities))


def _format_entity_list(entities: Sequence[Mapping[str, Any]]) -> str:
    return ", ".join(f"{entity['type']}={entity['value']}" for entity in entities)


def build_ticket_vector_doc(ticket: Mapping[str, Any]) -> dict[str, Any]:
    """Build a deterministic C19 document from a valid C6 Ticket."""
    validated = _validate_ticket(ticket)
    verdict = validated["verdict"] or {}
    template = _DECIDED_TICKET_TEMPLATE.read_text(encoding="utf-8")
    text = template.format(
        origin=validated["origin"],
        status=validated["status"],
        handling_type=validated["handling_type"],
        specialist=validated["specialist"],
        verdict=verdict.get("verdict") or "pending",
        confidence=verdict.get("confidence") if verdict else "pending",
        entities=_format_entity_list(validated["entities"]),
        summary=verdict.get("summary") or "",
        recommended_action=verdict.get("recommended_action") or "",
    )
    doc_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"0-ticket-soc:closed-ticket:{validated['ticket_id']}",
    ).hex
    return validate_contract(
        "VectorDoc",
        {
            "doc_id": f"doc_{doc_id}",
            "collection": "closed_tickets",
            "text": text.strip(),
            "source_kind": "ticket",
            "source_id": validated["ticket_id"],
            "keywords": _entity_values(validated["entities"]),
            "created_at": validated["updated_at"],
            "expires_at": None,
        },
    ).model_dump(mode="json")


class VectorTicketService:
    """Implement ``TicketVectorSink`` and expose Ticket similarity search."""

    def __init__(self, store: VectorStore, embedder: Embedder, settings: Settings):
        self._store = store
        self._embedder = embedder
        self._settings = settings

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        vector_registry: PluginRegistry | None = None,
        embedder_registry: PluginRegistry | None = None,
    ) -> "VectorTicketService":
        store = open_vector_store(settings, registry=vector_registry)
        try:
            embedder = open_embedder(settings, registry=embedder_registry)
        except Exception as error:
            try:
                store.close()
            except Exception as close_error:
                error.add_note(f"VectorStore cleanup failed ({type(close_error).__name__})")
            raise
        return cls(store, embedder, settings)

    def add_decided_ticket(self, ticket: Mapping[str, Any]) -> None:
        """Embed and upsert a Ticket only after the C6 decision is final."""
        validated = _validate_ticket(ticket)
        if validated["status"] not in DECIDED_TICKET_STATUSES:
            raise TicketNotDecidedError("Ticket decision is not complete")
        document = build_ticket_vector_doc(validated)
        self._store.upsert(document, self._embed(document["text"]))

    def search_by_ticket(self, ticket: Mapping[str, Any], *, k: int = 5) -> list[tuple[str, float]]:
        """Search with a Ticket's fixed embedding text and exact entity values."""
        document = build_ticket_vector_doc(ticket)
        return self._search(document["text"], document["keywords"], k=k)

    def search_by_entities(
        self,
        entities: Sequence[Mapping[str, Any]],
        sentence: str,
        *,
        k: int = 5,
    ) -> list[tuple[str, float]]:
        """Search with entity values and a caller-provided sentence."""
        if not isinstance(sentence, str) or not sentence.strip():
            raise ValueError("search_sentence_required")
        validated_entities = _validated_entities(entities)
        template = _ENTITY_SENTENCE_TEMPLATE.read_text(encoding="utf-8")
        text = template.format(
            entities=_format_entity_list(validated_entities),
            sentence=sentence.strip(),
        )
        return self._search(text, _entity_values(validated_entities), k=k)

    def close(self) -> None:
        self._store.close()

    def _search(self, text: str, keywords: Sequence[str], *, k: int) -> list[tuple[str, float]]:
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            raise ValueError("search_limit_must_be_positive")
        candidate_limit = k * _CANDIDATE_MULTIPLIER
        query_vector = self._embed(text)
        keyword_hits = self._store.search_by_keywords(keywords, limit=candidate_limit)
        vector_hits = self._store.search_by_vector(query_vector, limit=candidate_limit)
        configured = self._settings.vector_search
        return fuse_search_results(
            configured.fusion_method,
            keyword_hits,
            vector_hits,
            k=k,
            keyword_weight=configured.keyword_weight,
            vector_weight=configured.vector_weight,
            rank_constant=configured.rrf_rank_constant,
        )

    def _embed(self, text: str) -> list[float]:
        vector = self._embedder.embed(text)
        expected = self._settings.embedder.dimensions
        if len(vector) != expected or any(
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            for value in vector
        ):
            raise ValueError("embedding_dimension_or_value_mismatch")
        return [float(value) for value in vector]
