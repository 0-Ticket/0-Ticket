"""UI 조회 전용 모델. 도메인 계약 자체에는 계산 필드를 추가하지 않는다."""

from typing import Literal

from pydantic import Field

from soc.api.models import _Model
from soc.contracts.generated.alert_schema import Alert
from soc.contracts.generated.case_schema import Case
from soc.contracts.generated.event_schema import Event
from soc.contracts.generated.incident_artifact_schema import IncidentArtifact
from soc.contracts.generated.incident_proposal_schema import IncidentProposal
from soc.contracts.generated.incident_schema import Incident
from soc.contracts.generated.raw_record_schema import RawRecord
from soc.contracts.generated.ticket_schema import Ticket

NormalizeStatus = Literal["pending", "succeeded", "failed"]
TicketStatus = Literal["new", "closed", "held", "escalated", "linked"]
TicketOrigin = Literal["auto", "scenario", "l1", "l3"]
IncidentStatus = Literal[
    "analyzing", "awaiting_review", "confirmed", "human_handling", "dismissed", "held"
]
CaseStatus = Literal["open", "in_progress", "resolved"]


class RawItem(_Model):
    raw_id: str
    record_id: str | None
    normalize_status: NormalizeStatus
    error_code: str | None
    fetched_at: int
    title: str | None
    severity: int | None
    seed_source: str | None


class RawPage(_Model):
    items: list[RawItem]
    next_cursor: str | None


class RawDetail(_Model):
    raw_record: RawRecord
    record: Alert | Event | None
    normalize_status: NormalizeStatus
    error_code: str | None
    seed_source: str | None


class TicketIncident(_Model):
    """Ticket이 붙은 Incident 요약. 필드 이름과 계산은 IncidentItem과 같다(#345)."""

    id: str
    title: str
    status: IncidentStatus
    severity: int
    assessed_severity: int | None
    display_severity: int


class TicketItem(_Model):
    id: str
    title: str
    origin: TicketOrigin
    status: TicketStatus
    severity: int = Field(ge=0, le=6)
    created_at: int
    updated_at: int
    seed_source: str | None
    incident: TicketIncident | None


class TicketPage(_Model):
    items: list[TicketItem]
    next_cursor: str | None


class AlertSummary(_Model):
    """Ticket 상세의 원본 Alert 요약. Alert를 하나씩 조회하지 않게 한 번에 준다(#365)."""

    id: str
    title: str
    time: int
    severity: int = Field(ge=0, le=6)


class TicketDetail(_Model):
    ticket: Ticket
    alerts: list[AlertSummary]
    severity: int
    seed_source: str | None
    incident: TicketIncident | None


class IncidentItem(_Model):
    id: str
    title: str
    status: IncidentStatus
    severity: int
    assessed_severity: int | None
    display_severity: int
    analysis_round: int
    updated_at: int
    seed_source: str | None


class IncidentPage(_Model):
    items: list[IncidentItem]
    next_cursor: str | None


class GraphNode(_Model):
    id: str
    kind: Literal["ticket", "alert", "hunt", "entity", "incident"]
    type: str | None = None
    value: str | None = None


class GraphEdge(_Model):
    from_: str = Field(alias="from")
    to: str
    kind: str


class GraphPath(_Model):
    incident_id: str
    ticket_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class IncidentTicketGraph(_Model):
    ticket_id: str
    coverage: Literal["complete", "incomplete", "legacy", "unknown"]
    reason: str | None
    paths: list[GraphPath]


class IncidentTicket(_Model):
    """Incident 상세의 소속 Ticket. 제목은 Ticket이 만들어질 때의 값이다(D-070)."""

    id: str
    title: str


class IncidentDetail(_Model):
    incident: Incident
    tickets: list[IncidentTicket]
    artifacts: list[IncidentArtifact]
    proposals: list[IncidentProposal]
    ticket_graphs: list[IncidentTicketGraph] = Field(default_factory=list)
    seed_source: str | None


class ReviewResult(_Model):
    """승인·반려 결과. 승인이면 만든 Case의 id, 반려이면 null(#365, D-076)."""

    incident: IncidentItem
    case_id: str | None


class CaseItem(_Model):
    id: str
    incident_id: str
    title: str
    severity: int
    status: CaseStatus
    confirmed_at: int
    seed_source: str | None


class CasePage(_Model):
    items: list[CaseItem]
    next_cursor: str | None


class CaseDetail(_Model):
    case: Case
    seed_source: str | None


class NormalizeCounts(_Model):
    succeeded: int
    failed: int
    pending: int
    success_ratio: float | None


class HuntingCounts(_Model):
    statuses: dict[str, int]
    total: int
    promoted: int
    promotion_ratio: float | None


class Dashboard(_Model):
    flow: dict[str, int]
    ticket_status: dict[str, int]
    incident_status: dict[str, int]
    case_status: dict[str, int]
    ticket_severity: dict[str, int]
    normalization: dict[str, NormalizeCounts]
    hunting: HuntingCounts
    analyzed_incidents: list[IncidentItem]
    top_incidents: list[IncidentItem]
