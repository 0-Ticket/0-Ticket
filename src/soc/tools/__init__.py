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
    """운영 레지스트리: 내부 데이터 4개, SIEM 2개(#212), SSH 점검 1개(#213),
    위협 인텔 조회 1개(#309), 로컬 ATT&CK·KEV 조회 3개(#311),
    유사 사례 검색 1개(#313), 확정 Case 검색 1개(#392).

    Web 도구(`query_http_flow`·`summarize_http_flow`)는 #382에서 없앴다. 그 둘은 OCSF
    4002 Event만 읽었고, 이벤트 정규화가 사라져 4002 행이 더 생기지 않는다(D-085).
    """
    from soc.tools.confirmed_cases import SEARCH_CONFIRMED_CASES
    from soc.tools.internal import INTERNAL_TOOLS
    from soc.tools.local_intel import LOCAL_INTEL_TOOLS
    from soc.tools.siem import siem_tools
    from soc.tools.similar_cases import SEARCH_SIMILAR_CASES
    from soc.tools.ssh import RUN_HOST_CHECK
    from soc.tools.threat_intel import lookup_indicator_tool

    return ToolRegistry(
        [
            *INTERNAL_TOOLS,
            *siem_tools(),
            RUN_HOST_CHECK,
            lookup_indicator_tool(),
            *LOCAL_INTEL_TOOLS,
            SEARCH_SIMILAR_CASES,
            SEARCH_CONFIRMED_CASES,
        ]
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
