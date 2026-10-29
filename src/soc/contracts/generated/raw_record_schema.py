# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, constr


class RawRecord(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    raw_id: constr(pattern=r"^raw_", strict=True)
    source_type: StrictStr
    received_at: StrictInt
    payload: StrictStr
    sha256: StrictStr
