# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, constr


class Parse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    field: constr(min_length=1, strict=True)
    pattern: constr(min_length=1, strict=True)


class AliasTable(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    scenario: StrictStr
    kind: Literal["alert", "event"]
    class_uid: StrictInt | None
    activity: StrictStr | None
    fields: dict[str, list[StrictStr]]
    time_format: StrictStr
    severity_map: dict[str, Any] | None
    default_techniques: list[StrictStr] | None
    extensions_map: dict[str, Any] | None
    parse: Parse | None
