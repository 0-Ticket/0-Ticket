# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class IngestCheckpoint(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    siem_profile: Annotated[
        str,
        Field(
            description="가져온 SIEM 연결 프로필 이름. RawRecord의 siem_profile과 같다",
            min_length=1,
        ),
    ]
    source_kind: Literal["alert", "event"]
    source_key: Annotated[
        str,
        Field(
            description="설정에 적은 조회 대상. ELK는 alias 또는 인덱스·데이터 스트림 패턴",
            min_length=1,
        ),
    ]
    cursor: Annotated[
        dict[str, Any],
        Field(
            description='다음 실행이 이어서 조회할 위치. 안쪽 모양은 수집기가 정한다(예: {"time_ms": 1730000000000})'
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
