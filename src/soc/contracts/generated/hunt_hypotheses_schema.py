# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from .common import types_schema

type AttackTechnique = Annotated[str, Field(pattern="^T[0-9]{4}(\\.[0-9]{3})?$")]


type NewsId = Annotated[int, Field(ge=1)]


class HuntHypothesis(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    hypothesis: Annotated[str, Field(description="가설 문장", min_length=1)]
    attack_techniques: Annotated[
        list[AttackTechnique],
        Field(
            description="ATT&CK 기법 ID(T1190, T1059.004). 1개 이상, 중복 없음. 실제로 있는 기법인지는 L3 코드가 확인한다",
            min_length=1,
        ),
    ]
    news_ids: Annotated[
        list[NewsId],
        Field(
            description="참고한 뉴스(threat_news.id). 중복 없음. 입력에 없던 값은 L3 코드가 버린다"
        ),
    ]
    case_ids: Annotated[
        list[types_schema.CaseId],
        Field(description="참고한 Case ID. 중복 없음. 입력에 없던 값은 L3 코드가 버린다"),
    ]


class HuntHypotheses(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    hypotheses: Annotated[
        list[HuntHypothesis], Field(description="가설 목록. 가설을 세우지 못하면 빈 목록")
    ]
