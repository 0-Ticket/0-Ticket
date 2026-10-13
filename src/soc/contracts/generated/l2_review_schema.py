# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, conint, constr


class L2Review(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    incident_id: constr(pattern=r"^in_", strict=True)
    reviewer: StrictStr
    decision: Literal["approve", "reject"]
    reject_type: Literal["wrong_grouping", "missing_step", "wrong_conclusion"] | None
    comment: StrictStr | None
    round: conint(ge=1, strict=True)
    created_at: StrictInt
