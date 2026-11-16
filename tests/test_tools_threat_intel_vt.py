"""실제 VirusTotal로 lookup_indicator를 부른다(#309). 기본 실행과 CI에서는 빠진다(virustotal 마커).

실행 방법은 docs/notes/309-virustotal-lookup.md "확인 방법"에 있다. VT_API_KEY 환경변수가 필요하다.
무료 키 한도(분당 4건)를 지키려고 세 종류를 한 번씩만 부르고, 응답 내용은 출력하지 않고
status·건수·걸린 시간만 본다. 환경변수가 없으면 건너뛰지 않고 실패한다.
"""

import asyncio
import os
import time

import pytest
from test_agent_core import CONFIG
from tool_helpers import Caller, parse

from soc.tools import ToolRegistry
from soc.tools.threat_intel import lookup_indicator_tool

pytestmark = pytest.mark.virustotal
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
TI = {
    "api_key_env": "VT_API_KEY",
    "connect_timeout_seconds": 5,
    "read_timeout_seconds": 10,
    "deadline_seconds": 15,
    "max_bytes": 1_048_576,
    "per_minute": 4,
    "per_day": 500,
    "cache_ttl_seconds": 86_400,
    "cache_max_entries": 100,
    "exclude_cidrs": [],
    "exclude_domains": [],
}


def test_real_lookups_return_a_summary() -> None:
    assert os.environ.get("VT_API_KEY"), "VT_API_KEY가 없다"
    tools = {**CONFIG["tools"], "threat_intel": TI, "allowed": {"l1": ["lookup_indicator"]}}
    c = Caller(ToolRegistry([lookup_indicator_tool()]), {**CONFIG, "tools": tools})
    for kind, value in (("ip", "8.8.8.8"), ("domain", "example.com"), ("hash", EMPTY_SHA256)):
        started = time.monotonic()
        out = parse(asyncio.run(c("lookup_indicator", {"indicator_type": kind, "value": value})))
        elapsed = time.monotonic() - started
        print(f"{kind}: status={out['status']} malicious={out.get('malicious')} {elapsed:.2f}s")
        assert out["status"] in ("found", "not_found"), out
        if out["status"] == "found":
            assert isinstance(out["malicious"], int)
    again = parse(asyncio.run(c("lookup_indicator", {"indicator_type": "ip", "value": "8.8.8.8"})))
    assert again["from_cache"] is True
