# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, StrictStr


class Ioc(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: StrictStr
    value: StrictStr
