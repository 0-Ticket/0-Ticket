# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import types_schema

type DetectionRule = Annotated[str, Field(min_length=1)]


type ResponseAction = Annotated[str, Field(min_length=1)]


class Technique(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[str, Field(pattern="^T[0-9]{4}(\\.[0-9]{3})?$")]
    evidence_ids: Annotated[list[types_schema.EvidenceId], Field(min_length=1)]


class IncidentAnalysis(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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
    techniques: list[Technique]
    impact: str
    cause: str
    further_risk: str
    detection_rules: list[DetectionRule]
    response_actions: list[ResponseAction]
    evidence_ids: Annotated[
        list[types_schema.EvidenceId],
        Field(description="어느 기법에도 붙지 않은 근거. 비어도 된다"),
    ]
