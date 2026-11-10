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


class TicketItem(_Model):
    id: str
    origin: TicketOrigin
    status: TicketStatus
    severity: int = Field(ge=0, le=6)
    created_at: int
    updated_at: int
    seed_source: str | None


class TicketPage(_Model):
    items: list[TicketItem]
    next_cursor: str | None


class TicketDetail(_Model):
    ticket: Ticket
    severity: int
    seed_source: str | None


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


class IncidentDetail(_Model):
    incident: Incident
    artifacts: list[IncidentArtifact]
    proposals: list[IncidentProposal]
    seed_source: str | None


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
