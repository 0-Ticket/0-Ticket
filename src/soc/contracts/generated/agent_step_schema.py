# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, conint, constr


class AgentStep(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    subject_type: Literal["ticket", "incident", "hunt"]
    subject_id: StrictStr
    step: conint(ge=1, strict=True)
    agent: StrictStr
    action: Literal["llm_call", "tool_call", "decision"]
    tool: StrictStr | None
    prompt_version: StrictStr | None
    input_excerpt: constr(max_length=2000, strict=True)
    output_excerpt: constr(max_length=2000, strict=True)
    model: StrictStr | None
    tokens: StrictInt | None
    latency_ms: StrictInt
    created_at: StrictInt
