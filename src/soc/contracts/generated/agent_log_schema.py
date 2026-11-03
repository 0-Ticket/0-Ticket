# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

type TokensIn = Annotated[
    int, Field(description="모델 호출만. 도구 호출은 null", ge=0, le=2147483647)
]


type TokensOut = Annotated[
    int, Field(description="모델 호출만. 도구 호출은 null", ge=0, le=2147483647)
]


class AgentLog(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[
        str,
        Field(pattern="^agl_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ]
    run_id: Annotated[
        str,
        Field(pattern="^run_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ]
    stage: Literal["l1", "l2", "l3"]
    subject_type: Annotated[
        Literal["alert", "ticket", "incident", "hunt"],
        Field(description="alert는 L1 1차 판정"),
    ]
    subject_id: Annotated[str, Field(description="대상 ID")]
    seq: Annotated[
        int, Field(description="작업 안 순번. (run_id, seq)는 유일", ge=1, le=2147483647)
    ]
    kind: Literal["model", "tool"]
    name: Annotated[str, Field(description="모델 이름 또는 도구 이름")]
    input: Annotated[
        Any, Field(description="입력 전체(JSON 값). 공격자가 쓴 문자열이 들어갈 수 있다")
    ]
    output: Annotated[Any, Field(description="출력 전체(JSON 값). 실패해 출력이 없으면 null")]
    outcome: Literal["ok", "error"]
    tokens_in: Annotated[TokensIn | None, Field(description="모델 호출만. 도구 호출은 null")]
    tokens_out: Annotated[TokensOut | None, Field(description="모델 호출만. 도구 호출은 null")]
    started_at: Annotated[
        int,
        Field(
            description="UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)",
            ge=0,
            le=253402214399999,
        ),
    ]
    duration_ms: Annotated[int, Field(ge=0, le=2147483647)]
    details: Annotated[dict[str, Any], Field(description="계약에 없는 값. 다른 단계는 읽지 않는다")]
