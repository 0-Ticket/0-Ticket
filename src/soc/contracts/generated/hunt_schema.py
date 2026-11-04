# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import entity_schema, types_schema

type AttackTechnique = Annotated[str, Field(pattern="^T[0-9]{4}(\\.[0-9]{3})?$")]


type Confidence = Annotated[
    float,
    Field(
        description="검증 결과 확신도. confirmed, rejected, inconclusive일 때만 값이 있다",
        ge=0.0,
        le=1.0,
    ),
]


class Hunt(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[
        str,
        Field(pattern="^hnt_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ]
    hunt_run_id: Annotated[
        str,
        Field(
            description="같은 가설 생성 실행에서 나온 Hunt 묶음. Agent Log의 run_id(에이전트 실행 한 번)와 다른 ID다",
            pattern="^hrn_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        ),
    ]
    status: Annotated[
        Literal["pending", "confirmed", "rejected", "inconclusive", "failed"],
        Field(
            description="pending: 검증 대기(재시도 대기 포함), confirmed: 위협 발견(L3 Ticket을 만든다), rejected: 가설 기각, inconclusive: 근거 부족, failed: 검증 run이 재시도 한도까지 실패. 모두 L3가 바꾼다"
        ),
    ]
    hypothesis: Annotated[
        str,
        Field(
            description="가설 문장. 밖에서 온 문자열(뉴스 등)에서 나온 LLM 출력이라 공격자가 쓴 문장이 들어갈 수 있다",
            min_length=1,
        ),
    ]
    attack_techniques: Annotated[
        list[AttackTechnique],
        Field(description="ATT&CK 기법 ID(T1190, T1059.004). 중복 없음, 빈 목록 가능"),
    ]
    confidence: Annotated[
        Confidence | None,
        Field(description="검증 결과 확신도. confirmed, rejected, inconclusive일 때만 값이 있다"),
    ]
    reason: Annotated[
        str | None,
        Field(
            description="검증 결과 이유. confirmed, rejected, inconclusive일 때만 값이 있다. 공격자가 쓴 문장이 들어갈 수 있다",
            min_length=1,
        ),
    ]
    evidence_ids: Annotated[
        list[types_schema.EvidenceId],
        Field(
            description="검증 근거가 된 Alert·Event ID와 도구 호출 기록 ID. confirmed는 Alert·Event ID가 1개 이상, rejected는 1개 이상. 중복 없음"
        ),
    ]
    entities: Annotated[list[entity_schema.Entity], Field(description="검증에서 확인한 엔티티")]
    attempts: Annotated[
        int, Field(description="검증 run 시도 횟수. pending이 아니면 1 이상", ge=0, le=2147483647)
    ]
    verified_at: Annotated[
        types_schema.EpochMs | None,
        Field(
            description="검증 결과가 정해진 시각. confirmed, rejected, inconclusive일 때만 값이 있다"
        ),
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
    details: Annotated[
        dict[str, Any],
        Field(description="가설 출처(뉴스·Case 참조) 등 L3 내부 값. 다른 단계는 읽지 않는다"),
    ]
