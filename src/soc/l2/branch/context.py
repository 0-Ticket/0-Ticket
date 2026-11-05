"""조회 결과를 분류 문맥으로 만든다."""

from dataclasses import dataclass
from typing import Any

from soc.l2.branch.read import BranchRows


@dataclass(frozen=True)
class BranchContext:
    ticket: dict[str, Any]
    alerts: tuple[dict[str, Any], ...]
    events: tuple[dict[str, Any], ...]
    hunt: dict[str, Any] | None
    evidence_ids: tuple[str, ...]
    missing_evidence_count: int


def build_context(rows: BranchRows) -> BranchContext:
    """조회한 Ticket·Alert·Event·Hunt와 확인된 근거를 그대로 문맥으로 만든다."""
    return BranchContext(
        ticket=rows.ticket,
        alerts=rows.alerts,
        events=rows.events,
        hunt=rows.hunt,
        evidence_ids=rows.evidence_ids,
        missing_evidence_count=rows.missing_evidence_count,
    )
