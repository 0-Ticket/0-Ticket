# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class IngestQuarantine(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    siem_profile: Annotated[str, Field(min_length=1)]
    source_kind: Literal["alert", "event"]
    source_key: Annotated[str, Field(min_length=1)]
    siem_ref: Annotated[
        str, Field(description="위치와 안정 해시를 담은 격리 전용 합성 키", min_length=1)
    ]
    reason_code: Annotated[str, Field(pattern="^[a-z][a-z0-9_]*$")]
    original_text: Annotated[
        str,
        Field(description="격리 전 원문을 json.dumps(ensure_ascii=True) 규칙으로 직렬화한 글자"),
    ]
    seen_at: Annotated[
        int,
        Field(
            description="UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)",
            ge=0,
            le=253402214399999,
        ),
    ]
