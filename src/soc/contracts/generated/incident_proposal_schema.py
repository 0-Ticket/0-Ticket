# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class IncidentProposal(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[
        str,
        Field(pattern="^prp_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ]
    artifact_id: Annotated[
        str,
        Field(pattern="^art_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ]
    kind: Literal["response", "detection"]
    seq: Annotated[
        int,
        Field(description="한 Artifact의 권고 조치 목록 전체의 순서(1부터)", ge=1, le=2147483647),
    ]
    priority: Annotated[
        Literal["high", "medium", "low"] | None,
        Field(description="옛 구조에서 옮긴 행(마이그레이션 0202)은 null"),
    ]
    title: Annotated[
        str,
        Field(
            description="한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. 옛 행은 본문 첫 줄을 정리한 값",
            max_length=200,
            min_length=1,
            pattern="^[\\t\\n\\u000b\\f\\r \\u00a0\\u3000]*[^\\t\\n\\u000b\\f\\r \\u00a0\\u3000][\\s\\S]*$",
        ),
    ]
    detail: Annotated[
        str,
        Field(
            description="구체적인 조치. 탐지 룰이면 룰 내용. 길이 한도는 분석 출력 계약만 지킨다(옛 body가 더 길 수 있다)",
            min_length=1,
        ),
    ]
    rationale: Annotated[
        str | None, Field(description="이 사건의 어떤 사실 때문에 필요한지. 옛 행은 null")
    ]
    created_at: Annotated[
        int,
        Field(
            description="UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)",
            ge=0,
            le=253402214399999,
        ),
    ]
