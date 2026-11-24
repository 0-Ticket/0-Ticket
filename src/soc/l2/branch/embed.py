"""분류용 Ticket을 색인과 질의에서 같은 구조화 텍스트로 만든다."""

from soc.contracts.alert import alert_rule_id, alert_title
from soc.contracts.event import EMPTY_SUMMARY, event_summary
from soc.entities import normalize_entity_value
from soc.l2.branch.context import BranchContext

MAX_TEXT_CHARS = 2048
MAX_LINE_CHARS = 256
MAX_ALERTS = 5
MAX_EVENTS = 5
MAX_ENTITIES = 20


def embedding_text(context: BranchContext) -> str:
    """제목·룰·엔티티·행위 요약을 합친다. 모델 판정 이유는 쓰지 않는다."""
    lines: list[str] = []
    seen: set[str] = set()

    def add(value: str | None, *, label: str = "") -> None:
        if not value:
            return
        cleaned = " ".join(value.split())[:MAX_LINE_CHARS]
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            lines.append(f"{label}{cleaned}")

    add(context.ticket.get("title"))
    for alert in context.alerts[:MAX_ALERTS]:
        title = alert_title(alert)
        add(title)
        add(alert_rule_id(alert) or alert.get("details", {}).get("rule_id"), label="rule: ")
        message = alert.get("message")
        if message != title:
            add(message, label="alert: ")

    entities = context.ticket.get("entities") or [
        entity
        for alert in context.alerts
        for entity in alert.get("details", {}).get("entities", [])
    ]
    normalized = sorted(
        {
            (
                entity["type"],
                entity.get("role") or "none",
                normalize_entity_value(entity["type"], entity["value"]),
            )
            for entity in entities
        }
    )
    for kind, role, value in normalized[:MAX_ENTITIES]:
        add(f"type={kind} role={role} value={value}", label="entity: ")

    for event in context.events[:MAX_EVENTS]:
        summary = event_summary(event)
        if summary != EMPTY_SUMMARY:
            add(summary, label="event: ")
    if context.hunt is not None:
        add(context.hunt.get("hypothesis"), label="hunt: ")
    return "\n".join(lines)[:MAX_TEXT_CHARS]
