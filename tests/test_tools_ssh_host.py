"""실제 SSH 호스트 점검(#213, ssh 마커). 기본 실행과 CI에서 빠진다.

시연 랩의 데모 호스트(웹 서버 컨테이너)에 사람이 PC에서 돌린다. 실행 방법과 읽기 전용 계정
만드는 법은 docs/notes/213-ssh-tool.md. 필요한 것:
- config/local.toml(커밋 안 함)의 [[tools.ssh.hosts]]
- 환경변수 SSH_TOOL_PRIVATE_KEY(그 계정의 OpenSSH 개인 키 본문)

호스트마다 켜진 점검을 한 번씩 부르고, 종료 코드와 줄 수만 출력한다(docs/security.md "데이터").
"""

import asyncio
import json
from pathlib import Path

import pytest
from test_agent_core import CONFIG
from tool_helpers import Caller, parse

from soc.agent.config import load_config
from soc.tools import ToolRegistry
from soc.tools.ssh import RUN_HOST_CHECK

pytestmark = pytest.mark.ssh

REPO = Path(__file__).resolve().parents[1]
# file_hash는 데모 호스트에 늘 있는 파일로 본다
HASH_PATH = "/etc/hostname"


def test_enabled_checks_run_on_configured_hosts() -> None:
    tools = load_config(REPO / "config")["tools"]
    hosts = tools["ssh"]["hosts"]
    assert hosts, "config/local.toml에 [[tools.ssh.hosts]]가 없다"
    cfg = {**CONFIG, "tools": {**tools, "allowed": {"l2": ["run_host_check"]}}}
    caller = Caller(ToolRegistry([RUN_HOST_CHECK]), cfg, stage="l2")
    for host in hosts:
        for check in host["checks"]:
            arguments = {"host": host["name"], "check": check}
            if check == "file_hash":
                arguments["path"] = HASH_PATH
            text = asyncio.run(caller("run_host_check", json.dumps(arguments)))
            out = parse(text)  # TOOL_ERROR면 여기서 실패한다
            lines = len(out["stdout"].splitlines())
            print(f"{host['name']} {check}: exit_status={out['exit_status']} lines={lines}")
            assert out["exit_status"] is not None or out["stdout_truncated"]
