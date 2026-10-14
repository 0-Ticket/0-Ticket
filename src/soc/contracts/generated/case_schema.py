# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, constr

from . import case_task_schema


class Case(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    case_id: constr(pattern=r"^cs_", strict=True)
    incident_id: constr(pattern=r"^in_", strict=True)
    title: StrictStr
    status: Literal["open", "responding", "closed"]
    tasks: list[case_task_schema.CaseTask]
    lessons: StrictStr | None
    extensions: dict[constr(pattern=r"^[^.]+\..+$", strict=True), Any]
    created_at: StrictInt
    closed_at: StrictInt | None
