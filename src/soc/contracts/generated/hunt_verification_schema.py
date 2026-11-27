# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import entity_schema, types_schema


class HuntVerification(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    result: Annotated[
        Literal["confirmed", "rejected", "inconclusive"],
        Field(description="confirmed: 위협 확인, rejected: 가설 기각, inconclusive: 근거 부족"),
    ]
    confidence: Annotated[float, Field(description="확신도", ge=0.0, le=1.0)]
    reason: Annotated[
        str, Field(description="이유. 공격자가 쓴 문장이 들어갈 수 있다", min_length=1)
    ]
    evidence_ids: Annotated[
        list[types_schema.EvidenceId],
        Field(description="근거가 된 Alert·Event ID와 도구 호출 기록 ID. 중복 없음"),
    ]
    siem_refs: Annotated[
        list[types_schema.SiemRef],
        Field(
            description="검증 근거로 쓰려고 고른 SIEM 문서의 저장 키(#382). evidence_ids와 별개다(아직 ID가 없다). 이 run의 도구 결과에 보인 것만 쓸 수 있고, 워커가 가져와 저장한 뒤 evt_ ID를 발급해 evidence_ids에 더한다. 중복 없음"
        ),
    ]
    entities: Annotated[
        list[entity_schema.Entity],
        Field(description="모델이 확인한 엔티티. L3 코드가 근거 레코드의 엔티티와 합친다"),
    ]
