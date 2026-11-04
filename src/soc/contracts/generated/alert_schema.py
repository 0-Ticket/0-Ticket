# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import asset_schema, entity_schema, verdict_schema


class Ocsf(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    class_uid: Literal[2004]


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


class Alert(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[
        str,
        Field(pattern="^alt_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ]
    raw_id: Annotated[
        str,
        Field(pattern="^raw_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ]
    time: Annotated[
        int,
        Field(
            description="UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)",
            ge=0,
            le=253402214399999,
        ),
    ]
    severity: Annotated[
        int,
        Field(
            description="OCSF severity_id. 0 Unknown, 1 Informational, 2 Low, 3 Medium, 4 High, 5 Critical, 6 Fatal",
            ge=0,
            le=6,
        ),
    ]
    title: Annotated[str, Field(description="한 줄 요약(룰 이름 등)")]
    rule_id: Annotated[str | None, Field(description="알럿을 만든 SIEM 탐지 룰 ID. 없으면 null")]
    entities: list[entity_schema.Entity]
    assets: list[asset_schema.Asset]
    triage: Annotated[
        Triage | None,
        Field(description="시나리오 모드에서 일치하지 않은 알럿의 L1 1차 판정. 그 밖에는 null"),
    ]
    ocsf: Annotated[Ocsf, Field(description="OCSF Detection Finding 전체")]
    details: Annotated[dict[str, Any], Field(description="계약에 없는 값. 다른 단계는 읽지 않는다")]
