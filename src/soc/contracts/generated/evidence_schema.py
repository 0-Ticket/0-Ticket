# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, StrictStr


class Evidence(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ref_type: StrictStr
    ref_id: StrictStr
    note: StrictStr
