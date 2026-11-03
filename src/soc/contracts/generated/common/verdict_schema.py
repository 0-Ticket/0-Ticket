# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import types_schema


class Verdict(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    decision: Literal["benign", "malicious", "undetermined"]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    reason: Annotated[str, Field(description="판정 이유")]
    evidence_ids: Annotated[
        list[types_schema.EvidenceId],
        Field(
            description="판정 근거가 된 Alert·Event ID와 도구 호출 기록 ID. decision이 benign·malicious이면 1개 이상"
        ),
    ]
    decided_at: Annotated[
        int,
        Field(
            description="UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)",
            ge=0,
            le=253402214399999,
        ),
    ]
