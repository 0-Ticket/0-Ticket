# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import entity_schema, types_schema, verdict_schema


class Ticket(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[
        str,
        Field(pattern="^tkt_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ]
    origin: Annotated[
        Literal["auto", "scenario", "l1", "l3"],
        Field(
            description="auto: 기본 모드, scenario: 시나리오 일치, l1: L1 1차 판정으로 승격, l3: L3 헌팅 발견"
        ),
    ]
    status: Annotated[
        Literal["new", "closed", "held", "escalated", "linked"],
        Field(
            description="new: L1 판정 대기, closed: 오탐 종결, held: 보류, escalated: L2 대기, linked: Incident에 붙음"
        ),
    ]
    alert_ids: Annotated[
        list[types_schema.AlertId],
        Field(description="origin이 auto, scenario, l1이면 1개 이상"),
    ]
    entities: Annotated[
        list[entity_schema.Entity], Field(description="소속 Alert 엔티티를 모은 것")
    ]
    verdict: Annotated[
        verdict_schema.Verdict | None,
        Field(description="L1 Ticket 판정. status가 new이면 null"),
    ]
    created_at: Annotated[
        int,
        Field(
            description="UTC epoch 밀리초. 상한은 9999-12-31T23:59:59.999Z",
            ge=0,
            le=253402300799999,
        ),
    ]
    updated_at: Annotated[
        int,
        Field(
            description="UTC epoch 밀리초. 상한은 9999-12-31T23:59:59.999Z",
            ge=0,
            le=253402300799999,
        ),
    ]
    details: Annotated[dict[str, Any], Field(description="계약에 없는 값. 다른 단계는 읽지 않는다")]
