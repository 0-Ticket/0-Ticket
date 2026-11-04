# 생성 코드. 직접 고치지 않는다.
# contracts/의 JSON Schema를 고치고 scripts/generate_contracts.py를 실행한다.

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Entity(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Annotated[
        Literal["ip", "host", "user", "domain", "url", "file_hash", "process"],
        Field(description="엔티티 종류"),
    ]
    value: Annotated[str, Field(description="엔티티 값", min_length=1)]
    role: Annotated[
        Literal["src", "dst", "actor", "target"] | None,
        Field(description="역할. 모르면 null"),
    ]
