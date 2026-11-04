"""도구 테스트 도우미(#211). 레지스트리 세션을 SDK 없이 직접 부른다.

SDK가 하는 순서(on_tool_start → 도구 실행 → on_tool_end)를 그대로 흉내 내므로,
Agent Log tool 줄과 call_id가 실제 실행과 같은 방식으로 맞춰진다.
"""

import json
from types import SimpleNamespace
from typing import Any

from soc.agent.agent_log import LogRecorder
from soc.tools import RESULT_CLOSE, RESULT_OPEN, ToolRegistry, ToolSession

RUN_ID = "run_01a19f93-1150-7000-8000-000000000001"
SUBJECT = "alt_01a19f93-1150-7000-8000-000000000004"


def new_recorder(stage: str = "l1") -> LogRecorder:
    return LogRecorder(
        run_id=RUN_ID,
        stage=stage,
        subject_type="alert",
        subject_id=SUBJECT,
        model_name="fake-model",
        task="test",
        attempt=1,
        prompt_version="v",
    )


class Caller:
    """세션 하나와 기록기 하나로 도구를 부른다."""

    def __init__(
        self, registry: ToolRegistry, config: dict[str, Any], stage: str = "l1"
    ) -> None:
        self.recorder = new_recorder(stage)
        self.session: ToolSession = registry.session(
            stage=stage, config=config, recorder=self.recorder
        )
        self._n = 0

    async def __call__(self, name: str, arguments: Any) -> str:
        self._n += 1
        text = arguments if isinstance(arguments, str) else json.dumps(arguments)
        ctx = SimpleNamespace(tool_call_id=f"call_{self._n}", tool_arguments=text)
        tool = SimpleNamespace(name=name)
        await self.recorder.on_tool_start(ctx, None, tool)
        out = await self.session.invoke(name, text, ctx.tool_call_id)
        await self.recorder.on_tool_end(ctx, None, tool, out)
        return out

    @property
    def rows(self) -> list[dict[str, Any]]:
        return self.recorder.rows


def parse(text: str) -> dict[str, Any]:
    """<tool_result> 결과를 JSON으로 읽는다. 오류 문구면 실패한다."""
    assert text.startswith(RESULT_OPEN + "\n"), text[:80]
    assert text.endswith("\n" + RESULT_CLOSE), text[-80:]
    body = text[len(RESULT_OPEN) + 1 : -len(RESULT_CLOSE) - 1]
    return json.loads(body)


def body_chars(text: str) -> int:
    """감싸기 전 JSON 본문 글자 수(max_tool_result_chars로 세는 값)."""
    return len(text) - len(RESULT_OPEN) - len(RESULT_CLOSE) - 2
