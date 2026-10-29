# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr


class CaseTask(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    task: StrictStr
    owner: StrictStr
    due_at: StrictInt | None
    status: Literal["todo", "doing", "done"]
