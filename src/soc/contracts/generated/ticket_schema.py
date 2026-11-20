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
    title: Annotated[
        str,
        Field(
            description='사건 제목. auto·scenario·l1은 소속 alert 제목, l3는 Hunt 가설 문장을 공백 정리해 자른 값(D-070). 1~200자이고 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. pattern은 "공백 목록 밖 글자가 하나 이상"이라는 뜻이고(앞뒤를 고정하는 계약 규칙 때문에 ^…$로 쓴다) 공백 목록은 soc.ticketing.TITLE_SPACES·DB CHECK와 같다',
            max_length=200,
            min_length=1,
            pattern="^[\\t\\n\\u000b\\f\\r \\u00a0\\u3000]*[^\\t\\n\\u000b\\f\\r \\u00a0\\u3000][\\s\\S]*$",
        ),
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
        Field(description="origin이 auto, scenario, l1이면 Alert 하나만 가리킨다. 중복 없음"),
    ]
    hunt_id: Annotated[
        types_schema.HuntId | None,
        Field(
            description="이 Ticket을 만든 Hunt. origin이 l3이면 값이 있고, 그 밖에는 null. Hunt 하나에 Ticket 하나"
        ),
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
            description="UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)",
            ge=0,
            le=253402214399999,
        ),
    ]
    updated_at: Annotated[
        int,
        Field(
            description="UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)",
            ge=0,
            le=253402214399999,
        ),
    ]
    details: Annotated[dict[str, Any], Field(description="계약에 없는 값. 다른 단계는 읽지 않는다")]
