# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, constr


class VectorDoc(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    doc_id: constr(pattern=r"^doc_", strict=True)
    collection: StrictStr
    text: StrictStr
    source_kind: Literal["ticket", "incident", "case", "asset", "alert", "event"]
    source_id: StrictStr
    keywords: list[StrictStr]
    created_at: StrictInt
    expires_at: StrictInt | None
