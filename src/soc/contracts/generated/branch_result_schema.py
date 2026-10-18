# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, constr

from . import entity_schema
from .entity_schema import Entity as Entity_1


class Entity1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: StrictStr
    value: StrictStr


class Reason(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    rule_id: StrictStr
    entity: entity_schema.Entity | None


class Entity2(Entity_1):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: StrictStr
    value: StrictStr


class Reason1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    rule_id: StrictStr | None
    entity: Entity2 | Entity1 | None = Field(..., title="Entity")


class BranchResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    branch_id: constr(pattern=r"^br_", strict=True)
    subject_type: Literal["alert", "ticket"]
    subject_id: StrictStr
    path: Literal[
        "deduplicated",
        "excluded_shared_entity",
        "scenario_ticket",
        "l1_entity_lookup",
        "existing_incident",
        "new_incident",
    ]
    reason: Reason | Reason1
    created_at: StrictInt
