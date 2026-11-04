# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RawRecord(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[
        str,
        Field(pattern="^raw_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ]
    kind: Literal["alert", "event"]
    siem_profile: Annotated[str, Field(description="가져온 SIEM 연결 프로필 이름", min_length=1)]
    siem_ref: Annotated[
        str,
        Field(
            description="SIEM 안에서 문서 하나를 가리키는 값. ELK는 <_index>/<_id>", min_length=1
        ),
    ]
    fetched_at: Annotated[
        int,
        Field(
            description="UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)",
            ge=0,
            le=253402214399999,
        ),
    ]
    original: Annotated[dict[str, Any], Field(description="SIEM이 준 JSON 그대로")]
