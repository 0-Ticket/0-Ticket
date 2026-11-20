# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import types_schema


class Recommendation(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["response", "detection"]
    priority: Literal["high", "medium", "low"]
    title: Annotated[
        str,
        Field(
            description="한 줄. 공백(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)뿐인 값은 허용하지 않는다. Ticket 제목(D-070)과 같은 pattern",
            max_length=200,
            min_length=1,
            pattern="^[\\t\\n\\u000b\\f\\r \\u00a0\\u3000]*[^\\t\\n\\u000b\\f\\r \\u00a0\\u3000][\\s\\S]*$",
        ),
    ]
    detail: Annotated[
        str, Field(description="구체적인 조치. 탐지 룰이면 룰 내용", max_length=2000, min_length=1)
    ]
    rationale: Annotated[
        str, Field(description="이 사건의 어떤 사실 때문에 필요한지", max_length=1000, min_length=1)
    ]


class Technique(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[str, Field(pattern="^T[0-9]{4}(\\.[0-9]{3})?$")]
    evidence_ids: Annotated[list[types_schema.EvidenceId], Field(min_length=1)]


class IncidentAnalysis(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    verdict: Literal["not_threat", "attempted", "succeeded", "inconclusive"]
    title: Annotated[
        str,
        Field(
            description="사건을 한 줄로 설명하는 제목. 길이·pattern을 두지 않는다: 빈 값이나 긴 값이 계약 오류가 되면 분석 전체가 실패해 같은 Incident를 다시 분석한다(D-059 유형). 저장할 때 soc.ticketing.clean_title로 정리하고, 정리 결과가 폴백이면 Incident 제목을 덮어쓰지 않는다(D-072)"
        ),
    ]
    summary: Annotated[str, Field(min_length=1)]
    assessed_severity: Annotated[
        int,
        Field(
            description="OCSF severity_id. 0 Unknown, 1 Informational, 2 Low, 3 Medium, 4 High, 5 Critical, 6 Fatal",
            ge=0,
            le=6,
        ),
    ]
    techniques: list[Technique]
    impact: str
    cause: str
    further_risk: str
    recommendations: Annotated[
        list[Recommendation],
        Field(
            description="권고 조치. 대응과 탐지 룰을 한 목록에 둔다(D-072). 한도를 넘으면 자르지 않고 거부한다",
            max_length=10,
        ),
    ]
    evidence_ids: Annotated[
        list[types_schema.EvidenceId],
        Field(description="어느 기법에도 붙지 않은 근거. 비어도 된다"),
    ]
