"""조회 결과를 분류 문맥으로 만든다."""

from dataclasses import dataclass
from typing import Any

from soc.l2.branch.read import BranchRows
from soc.l2.branch.signals import EntitySignal, classify_entities
from soc.l2.config import BranchSettings


@dataclass(frozen=True)
class BranchContext:
    ticket: dict[str, Any]
    alerts: tuple[dict[str, Any], ...]
    events: tuple[dict[str, Any], ...]
    hunt: dict[str, Any] | None
    evidence_ids: tuple[str, ...]
    missing_evidence_count: int
    signals: tuple[EntitySignal, ...]


def build_context(rows: BranchRows, settings: BranchSettings) -> BranchContext:
    """Ticket과 L3 Hunt 엔티티를 합쳐 정규화한 신호도 함께 돌려준다."""
    entities = list(rows.ticket["entities"])
    if rows.hunt is not None:
        entities.extend(rows.hunt["entities"])
    return BranchContext(
        ticket=rows.ticket,
        alerts=rows.alerts,
        events=rows.events,
        hunt=rows.hunt,
        evidence_ids=rows.evidence_ids,
        missing_evidence_count=rows.missing_evidence_count,
        signals=classify_entities(entities, settings),
    )
