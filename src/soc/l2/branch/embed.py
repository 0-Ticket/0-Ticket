"""Ticket 분류 문맥을 Qdrant 검색용 평문으로 만든다."""

from soc.l2.branch.context import BranchContext


def embedding_text(context: BranchContext) -> str:
    """Alert 제목·Event 요약·판정 이유·Hunt 문장을 순서대로 줄바꿈 연결한다."""
    values = [*(alert["title"] for alert in context.alerts)]
    values.extend(event["summary"] for event in context.events)
    if context.ticket["verdict"] is not None:
        values.append(context.ticket["verdict"]["reason"])
    if context.hunt is not None:
        values.extend((context.hunt["hypothesis"], context.hunt["reason"]))
    return "\n".join(value for value in values if value)
