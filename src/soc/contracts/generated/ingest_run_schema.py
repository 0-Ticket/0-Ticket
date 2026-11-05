# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class IngestRun(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    siem_profile: Annotated[
        str,
        Field(
            description="가져온 SIEM 연결 프로필 이름. IngestCheckpoint의 siem_profile과 같다",
            min_length=1,
        ),
    ]
    source_kind: Literal["alert", "event"]
    source_key: Annotated[
        str,
        Field(
            description="설정에 적은 조회 대상. IngestCheckpoint의 source_key와 같다", min_length=1
        ),
    ]
    started_at: Annotated[
        int,
        Field(
            description="UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)",
            ge=0,
            le=253402214399999,
        ),
    ]
    finished_at: Annotated[
        int,
        Field(
            description="UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)",
            ge=0,
            le=253402214399999,
        ),
    ]
    outcome: Annotated[
        str,
        Field(
            description="성공이면 ok, 실패면 실패 원인의 종류 코드. 원문과 비밀은 넣지 않는다",
            pattern="^[a-z][a-z0-9_]*$",
        ),
    ]
    pages: Annotated[
        int,
        Field(description="저장까지 끝난 페이지 수. 빈 페이지는 세지 않는다", ge=0, le=2147483647),
    ]
    inserted: Annotated[
        int,
        Field(
            description="이 실행에서 새로 저장한 원본 수. 이미 있던 문서는 세지 않는다",
            ge=0,
            le=2147483647,
        ),
    ]
