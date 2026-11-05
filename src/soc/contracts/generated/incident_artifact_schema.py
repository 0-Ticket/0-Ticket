# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import types_schema


class TimelineItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    time: Annotated[
        int,
        Field(
            description="UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)",
            ge=0,
            le=253402214399999,
        ),
    ]
    summary: Annotated[str, Field(min_length=1)]
    evidence_ids: Annotated[list[types_schema.EvidenceId], Field(min_length=1)]


class Technique(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[str, Field(pattern="^T[0-9]{4}(\\.[0-9]{3})?$")]
    name: Annotated[str, Field(min_length=1)]
    evidence_ids: Annotated[list[types_schema.EvidenceId], Field(min_length=1)]


class IncidentArtifact(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[
        str,
        Field(pattern="^art_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ]
    incident_id: Annotated[
        str,
        Field(pattern="^inc_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ]
    analysis_round: Annotated[int, Field(ge=1, le=2147483647)]
    verdict: Literal["not_threat", "attempted", "succeeded", "inconclusive"]
    summary: Annotated[str, Field(min_length=1)]
    assessed_severity: Annotated[
        int,
        Field(
            description="OCSF severity_id. 0 Unknown, 1 Informational, 2 Low, 3 Medium, 4 High, 5 Critical, 6 Fatal",
            ge=0,
            le=6,
        ),
    ]
    timeline: list[TimelineItem]
    techniques: list[Technique]
    impact: str
    cause: str
    further_risk: str
    evidence_ids: list[types_schema.EvidenceId]
    created_at: Annotated[
        int,
        Field(
            description="UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)",
            ge=0,
            le=253402214399999,
        ),
    ]
