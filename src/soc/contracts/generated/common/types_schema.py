# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

type Types = Annotated[
    Any,
    Field(
        description="여러 계약이 함께 쓰는 값의 정의. ID는 접두사 + UUIDv7(소문자 16진수).",
        title="Types",
    ),
]


type EpochMs = Annotated[
    int,
    Field(
        description="UTC epoch 밀리초. 상한은 9999-12-30T23:59:59.999Z(+14시간 시간대로 읽어도 9999년 안)",
        ge=0,
        le=253402214399999,
    ),
]


type Severity = Annotated[
    int,
    Field(
        description="OCSF severity_id. 0 Unknown, 1 Informational, 2 Low, 3 Medium, 4 High, 5 Critical, 6 Fatal",
        ge=0,
        le=6,
    ),
]


type AlertId = Annotated[
    str,
    Field(pattern="^alt_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
]


type TicketId = Annotated[
    str,
    Field(pattern="^tkt_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
]


type IncidentId = Annotated[
    str,
    Field(pattern="^inc_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
]


type CaseId = Annotated[
    str,
    Field(pattern="^cas_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
]


type HuntId = Annotated[
    str,
    Field(pattern="^hnt_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
]


type HuntSubjectId = Annotated[
    str,
    Field(
        description="Agent Log의 hunt 대상. 가설 생성 run은 hrn_, 검증 run은 hnt_ ID",
        pattern="^(hnt|hrn)_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    ),
]


type EvidenceId = Annotated[
    str,
    Field(
        description="판정 근거. Alert·Event ID 또는 도구 호출 기록(Agent Log) ID",
        pattern="^(alt|evt|agl)_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    ),
]
