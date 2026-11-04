"""열린 Incident의 신호 겹침을 세어 후보 순위를 만든다."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from soc.l2.branch.signals import EntitySignal, classify_entities
from soc.l2.config import BranchSettings


@dataclass(frozen=True)
class Candidate:
    incident: dict[str, Any]
    strong_matches: int
    weak_matches: int


def rank_candidates(
    ticket_signals: Iterable[EntitySignal],
    incidents: Iterable[Mapping[str, Any]],
    settings: BranchSettings,
) -> tuple[Candidate, ...]:
    """공용 신호를 빼고 강한·보조 겹침과 updated_at으로 정렬한다."""
    ticket = tuple(ticket_signals)
    ticket_strong = {signal.key for signal in ticket if signal.level == "strong"}
    ticket_weak = {signal.key for signal in ticket if signal.level == "weak"}
    candidates = []
    for incident in incidents:
        signals = classify_entities(incident["entities"], settings)
        strong = {signal.key for signal in signals if signal.level == "strong"}
        weak = {signal.key for signal in signals if signal.level == "weak"}
        candidates.append(
            Candidate(
                dict(incident),
                strong_matches=len(ticket_strong & strong),
                weak_matches=len(ticket_weak & weak),
            )
        )
    candidates.sort(
        key=lambda item: (
            item.strong_matches,
            item.weak_matches,
            item.incident["updated_at"],
        ),
        reverse=True,
    )
    return tuple(candidates[: settings.max_candidates])
