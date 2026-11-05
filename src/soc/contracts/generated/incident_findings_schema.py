# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from .common import entity_schema, types_schema


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


class Entity(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    entity: entity_schema.Entity
    evidence_ids: Annotated[list[types_schema.EvidenceId], Field(min_length=1)]


class IncidentFindings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    timeline: list[TimelineItem]
    entities: list[Entity]
    evidence_ids: Annotated[
        list[types_schema.EvidenceId],
        Field(description="어느 항목에도 붙지 않은 근거. 비어도 된다"),
    ]
