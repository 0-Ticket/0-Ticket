"""에이전트 도구(도구 구현 방식, D-023, #211).

파이썬 함수 도구를 ToolRegistry에 ToolSpec으로 모으고, run_task가 실행마다 stage의 허용 목록
([tools.allowed])에 있는 것만 Agents SDK 함수 도구로 붙인다. MCP 노출은 필요해지면 이 위에 얹는다.
"""

from soc.tools.registry import (
    CUT_MARK,
    ERROR_CODES,
    RESULT_CLOSE,
    RESULT_OPEN,
    Arg,
    CallContext,
    ToolConfigError,
    ToolError,
    ToolRegistry,
    ToolSession,
    ToolSpec,
    tool_error_text,
)


def default_registry() -> ToolRegistry:
    """운영 레지스트리: 내부 데이터 3개, Web 2개, SIEM 2개(#212), SSH 점검 1개(#213),
    위협 인텔 조회 1개(#309)."""
    from soc.tools.internal import INTERNAL_TOOLS
    from soc.tools.siem import siem_tools
    from soc.tools.ssh import RUN_HOST_CHECK
    from soc.tools.threat_intel import lookup_indicator_tool
    from soc.tools.web import WEB_TOOLS

    return ToolRegistry(
        [*INTERNAL_TOOLS, *WEB_TOOLS, *siem_tools(), RUN_HOST_CHECK, lookup_indicator_tool()]
    )


__all__ = [
    "CUT_MARK",
    "ERROR_CODES",
    "RESULT_CLOSE",
    "RESULT_OPEN",
    "Arg",
    "CallContext",
    "ToolConfigError",
    "ToolError",
    "ToolRegistry",
    "ToolSession",
    "ToolSpec",
    "default_registry",
    "tool_error_text",
]
