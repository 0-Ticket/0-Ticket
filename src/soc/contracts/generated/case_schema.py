# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import entity_schema, types_schema


class Case(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[
        str,
        Field(pattern="^cas_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ]
    incident_id: Annotated[
        str,
        Field(pattern="^inc_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ]
    title: Annotated[str, Field(description="승인 시점 Incident 제목")]
    summary: Annotated[str | None, Field(description="승인 시점 Incident summary를 그대로 복사")]
    severity: Annotated[
        int, Field(description="승인 시점 assessed_severity, 없으면 severity", ge=0, le=6)
    ]
    entities: Annotated[list[entity_schema.Entity], Field(description="승인 시점 엔티티")]
    confirmed_by: Annotated[str, Field(description="승인한 사람")]
    confirmed_at: Annotated[int, Field(description="UTC epoch 밀리초", ge=0)]
    status: Annotated[
        Literal["open", "in_progress", "resolved"],
        Field(description="open → in_progress → resolved. 사람이 화면에서 바꾼다"),
    ]
    assignee: Annotated[str | None, Field(description="담당 분석가")]
    resolved_at: Annotated[
        types_schema.EpochMs | None,
        Field(description="status가 resolved이면 필수, 그 밖에는 null"),
    ]
    details: Annotated[dict[str, Any], Field(description="계약에 없는 값. 다른 단계는 읽지 않는다")]
