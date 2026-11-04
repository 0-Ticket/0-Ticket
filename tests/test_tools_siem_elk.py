"""실제 ELK로 SIEM 조회 도구를 부른다(#212). 기본 실행과 CI에서는 빠진다(elk 마커).

실행 방법은 docs/notes/212-siem-tools.md "확인 방법"에 있다. ELK_URL·ELK_API_KEY 환경변수와
config/local.toml(커밋 안 함)의 [[tools.siem.targets]]를 쓴다.
문서 내용은 출력하지 않고 건수만 본다.
요청은 기록하는 전송 계층을 거치고, POST /<index>/_search 밖의 요청이 나가면 실패한다.
"""

import asyncio
import os
import time
from typing import Any

import httpx
import pytest
from fake_siem import _violation
from test_agent_core import CONFIG
from tool_helpers import Caller, parse

from soc.agent.config import load_config
from soc.tools import ToolRegistry
from soc.tools.siem import TARGET_FILTERS, siem_tools

pytestmark = pytest.mark.elk
DAY_MS = 86_400_000


class RecordingTransport(httpx.HTTPTransport):
    """실제 네트워크로 보내되, 보낸 요청이 읽기 전용 모양인지 남긴다."""

    def __init__(self) -> None:
        super().__init__()
        self.violations: list[str] = []
        self.count = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.count += 1
        problem = _violation(request)
        if problem is not None:
            self.violations.append(problem)
            return httpx.Response(599)
        return super().handle_request(request)


@pytest.fixture
def setup() -> tuple[Caller, RecordingTransport, list[str]]:
    missing = [name for name in ("ELK_URL", "ELK_API_KEY") if not os.environ.get(name)]
    if missing:
        pytest.fail(f"환경변수가 없다: {', '.join(missing)} (docs/notes/212-siem-tools.md)")
    tools = load_config()["tools"]
    targets = [t["name"] for t in tools["siem"]["targets"]]
    config = {**CONFIG, "tools": {**tools, "allowed": {"l2": ["query_siem", "count_siem"]}}}
    transport = RecordingTransport()
    caller = Caller(ToolRegistry(siem_tools(transport=transport)), config, stage="l2")
    return caller, transport, targets


def call(caller: Caller, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    out = asyncio.run(caller(name, arguments))
    assert not out.startswith("TOOL_ERROR"), out  # 오류 문구에는 비밀 값·주소가 없다
    return parse(out)


def test_query_and_count_each_configured_target(setup: Any) -> None:
    caller, transport, targets = setup
    end = int(time.time() * 1000)
    span = {"start_ms": end - 7 * DAY_MS, "end_ms": end}
    for target in targets:
        result = call(caller, "query_siem", {"target": target, **span, "limit": 5})
        assert result["source"] == "siem" and result["schema"] == "ecs"
        assert len(result["hits"]) <= 5
        for hit in result["hits"]:
            assert "/" in hit["siem_ref"]
        field = TARGET_FILTERS[target][0]
        counted = call(caller, "count_siem", {"target": target, **span, "field": field})
        assert len(counted["buckets"]) <= 10
        # 내용은 출력하지 않는다. 건수만 남긴다(docs/security.md "데이터")
        print(
            f"{target}: query hits={len(result['hits'])} total={result['total']}"
            f"({result['total_relation']}), count {field} buckets={len(counted['buckets'])}"
        )
    assert transport.violations == []
    assert transport.count == 2 * len(targets)
