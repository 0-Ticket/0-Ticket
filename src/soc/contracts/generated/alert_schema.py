# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import asset_schema, entity_schema, verdict_schema


class Triage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    status: Annotated[
        Literal["pending", "promoted", "held"],
        Field(
            description="pending: 1차 판정 대기, promoted: Ticket으로 승격, held: 보류(Ticket 없음)"
        ),
    ]
    verdict: verdict_schema.Verdict | None


class Details(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: Annotated[
        str,
        Field(pattern="^alt_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ]
    raw_id: Annotated[
        str,
        Field(pattern="^raw_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ]
    rule_id: Annotated[
        str | None, Field(description="알럿을 만든 SIEM 탐지 룰 ID. 없으면 null(폴백은 항상 null)")
    ]
    entities: list[entity_schema.Entity]
    assets: list[asset_schema.Asset]
    triage: Annotated[
        Triage | None,
        Field(description="시나리오 모드에서 일치하지 않은 알럿의 L1 1차 판정. 그 밖에는 null"),
    ]


class Alert(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    class_uid: Annotated[
        Literal[2004, 0],
        Field(
            description="2004 Detection Finding. 해석할 수 없는 원본의 폴백 Alert만 0(Base Event)"
        ),
    ]
    time: Annotated[
        int, Field(description="OCSF 생성 시각(epoch 밀리초)", ge=0, le=253402214399999)
    ]
    severity_id: Annotated[
        Literal[0, 1, 2, 3, 4, 5, 6, 99],
        Field(
            description="OCSF 심각도. 0 Unknown, 1 Informational, 2 Low, 3 Medium, 4 High, 5 Critical, 6 Fatal, 99 Other"
        ),
    ]
    details: Annotated[
        Details,
        Field(
            description="우리 쪽 값. OCSF 속성 이름과 같은 키를 두지 않는다. 아래 6개는 필수이고 그 밖의 값(fallback 등)은 더 올 수 있다"
        ),
    ]
