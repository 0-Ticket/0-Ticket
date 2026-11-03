# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import entity_schema, types_schema


class Incident(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[
        str,
        Field(pattern="^inc_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ]
    title: Annotated[str, Field(description="L2가 정한 제목")]
    summary: Annotated[str | None, Field(description="분석 요약. L2가 채운다. 분석 전 null")]
    status: Annotated[
        Literal["analyzing", "awaiting_review", "confirmed", "human_handling", "dismissed"],
        Field(
            description="analyzing: L2 분석 필요·중, awaiting_review: 사람 검토 대기, confirmed: 사람 승인(Case 생성), human_handling: 사람이 직접 처리, dismissed: 위협 아님으로 종결"
        ),
    ]
    ticket_ids: Annotated[list[types_schema.TicketId], Field(min_length=1)]
    entities: Annotated[
        list[entity_schema.Entity], Field(description="소속 Ticket 엔티티를 모은 것")
    ]
    severity: Annotated[
        int, Field(description="소속 Alert 심각도 중 최대. 소속 Alert가 없으면 0", ge=0, le=6)
    ]
    assessed_severity: Annotated[
        types_schema.Severity | None, Field(description="L2 분석이 판단한 심각도. 분석 전 null")
    ]
    analysis_round: Annotated[int, Field(description="L2 분석 횟수", ge=0)]
    review_round: Annotated[int, Field(description="사람 검토 횟수", ge=0)]
    created_at: Annotated[int, Field(description="UTC epoch 밀리초", ge=0)]
    updated_at: Annotated[int, Field(description="UTC epoch 밀리초", ge=0)]
    details: Annotated[dict[str, Any], Field(description="계약에 없는 값. 다른 단계는 읽지 않는다")]
