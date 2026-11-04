# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from .common import asset_schema, entity_schema


class Ocsf(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    class_uid: int


class Event(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[
        str,
        Field(pattern="^evt_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
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
    ocsf_class: Annotated[
        int,
        Field(
            description="OCSF class_uid. ocsf.class_uid와 같아야 한다(validate_contract 추가 검사)",
            ge=0,
            le=2147483647,
        ),
    ]
    summary: Annotated[str, Field(description="한 줄 요약")]
    entities: list[entity_schema.Entity]
    assets: list[asset_schema.Asset]
    ocsf: Annotated[Ocsf, Field(description="매핑한 OCSF 클래스 전체")]
    details: Annotated[dict[str, Any], Field(description="계약에 없는 값. 다른 단계는 읽지 않는다")]
