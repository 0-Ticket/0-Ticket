# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import types_schema


class BranchDecision(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    decision: Annotated[
        Literal["new", "existing"],
        Field(description="새 Incident를 만들지, 입력 후보 하나에 붙일지"),
    ]
    incident_id: Annotated[
        types_schema.IncidentId | None,
        Field(
            description="existing이면 후보 Incident ID, new이면 null. 실제 후보인지는 코드가 확인한다"
        ),
    ]
    confidence: Annotated[
        float, Field(description="분류 확신도. 기록만 하고 판정 임계로 쓰지 않는다", ge=0.0, le=1.0)
    ]
    reason: Annotated[str, Field(description="분류 이유", min_length=1)]
    similar_ticket_ids: Annotated[
        list[types_schema.TicketId],
        Field(
            description="입력에 보인 비슷한 Ticket ID의 부분집합. 실제 부분집합인지는 코드가 확인한다"
        ),
    ]
