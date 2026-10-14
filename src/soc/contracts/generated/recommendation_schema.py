# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr


class Recommendation(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    action: StrictStr
    risk: Literal["low", "medium", "high"]
    reversible: StrictBool
