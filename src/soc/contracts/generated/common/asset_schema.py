# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

type Criticality = Annotated[int, Field(description="중요도 1~5. 5가 가장 중요", ge=1, le=5)]


class Asset(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    entity_value: Annotated[
        str, Field(description="어느 엔티티의 자산 정보인지(Entity.value)", min_length=1)
    ]
    name: Annotated[str | None, Field(description="자산 이름")]
    criticality: Annotated[Criticality | None, Field(description="중요도 1~5. 5가 가장 중요")]
    owner: Annotated[str | None, Field(description="담당 부서·사람")]
