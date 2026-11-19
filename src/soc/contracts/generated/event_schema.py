# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import asset_schema, entity_schema


class Details(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    id: Annotated[
        str,
        Field(pattern="^evt_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ]
    raw_id: Annotated[
        str,
        Field(pattern="^raw_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"),
    ]
    entities: list[entity_schema.Entity]
    assets: list[asset_schema.Asset]


class Event(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    class_uid: Annotated[
        Literal[0, 2003, 3002, 4001, 4002, 4003, 6003],
        Field(
            description="OCSF 클래스. 0 Base Event, 2003 Compliance Finding, 3002 Authentication, 4001 Network Activity, 4002 HTTP Activity, 4003 DNS Activity, 6003 API Activity"
        ),
    ]
    time: Annotated[
        int, Field(description="활동 발생 시각(epoch 밀리초)", ge=0, le=253402214399999)
    ]
    severity_id: Annotated[
        Literal[0, 1, 2, 3, 4, 5, 6, 99],
        Field(
            description="OCSF 심각도. 0 Unknown, 1 Informational, 2 Low, 3 Medium, 4 High, 5 Critical, 6 Fatal, 99 Other"
        ),
    ]
    message: Annotated[
        str,
        Field(
            description="한 줄 요약. 공백이 아닌 글자가 하나 이상 있어야 한다. DB 컬럼 summary가 여기서 파생된다",
            pattern="^[\\s\\S]*\\S[\\s\\S]*$",
        ),
    ]
    details: Annotated[
        Details,
        Field(
            description="우리 쪽 값. OCSF 속성 이름과 같은 키를 두지 않는다. 아래 4개는 필수이고 그 밖의 값은 더 올 수 있다"
        ),
    ]
