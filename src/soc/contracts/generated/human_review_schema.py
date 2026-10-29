# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr, constr


class HumanReview(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ticket_id: constr(pattern=r"^tk_", strict=True)
    reviewer: StrictStr
    decision: Literal["tp", "fp"]
    overturned: StrictBool
    reason: StrictStr | None
    created_at: StrictInt
