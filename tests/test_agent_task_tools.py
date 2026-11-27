"""도구 허용 목록을 태스크별로 둔다(#382, D-086). 가짜 도구로 돈다(DB·ELK 없음).

`runner.py`가 stage의 목록만 보던 탓에 L2 보고 태스크에도 심 조회가 붙었다. 보고가 siem_ref를
인용하면 발급할 다음 태스크가 없어 근거가 되지 못한다. 그래서 설정은 태스크별로 두고, 태스크 키가
없으면 단계 키로 내려간다(옛 설정). 배포 설정에는 단계 키가 없어서 등록되지 않은 태스크는 도구가
하나도 붙지 않는다(기본 거부).
"""

from pathlib import Path
from typing import Any

from test_agent_core import CONFIG
from test_tools_registry import spec
from tool_helpers import new_recorder

from soc.agent.config import load_config
from soc.agent.types import TASK_NAMES
from soc.tools import ToolRegistry

REPO = Path(__file__).resolve().parents[1]
REGISTRY = ToolRegistry([spec("probe", lambda args, ctx: [])])


def names(allowed: dict[str, Any], *, stage: str = "l2", task: str | None = None) -> list[str]:
    cfg = {**CONFIG, "tools": {**CONFIG["tools"], "allowed": allowed}}
    session = REGISTRY.session(stage=stage, task=task, config=cfg, recorder=new_recorder(stage))
    return [tool.name for tool in session.function_tools()]


def test_task_key_wins_over_stage_key() -> None:
    allowed = {"l2": [], "l2_investigate": ["probe"]}
    assert names(allowed, task="l2_investigate") == ["probe"]


def test_task_key_can_be_narrower_than_the_stage_key() -> None:
    allowed = {"l2": ["probe"], "l2_report": []}
    assert names(allowed, task="l2_report") == []


def test_stage_key_is_used_when_the_task_has_no_key() -> None:
    # 옛 설정과 테스트 하네스가 단계 키만 둔다.
    assert names({"l2": ["probe"]}, task="l2_investigate") == ["probe"]
    assert names({"l2": ["probe"]}, task=None) == ["probe"]


def test_no_task_key_and_no_stage_key_means_no_tools() -> None:
    assert names({"l2_report": ["probe"]}, task="l2_investigate") == []


# 배포 설정


def shipped() -> dict[str, Any]:
    return load_config(REPO / "config")["tools"]["allowed"]


def test_shipped_config_is_keyed_by_task_only() -> None:
    allowed = shipped()
    assert sorted(allowed) == sorted(TASK_NAMES)
    for stage in ("l1", "l2", "l3"):
        assert stage not in allowed, "단계 키가 남아 있으면 등록되지 않은 태스크가 도구를 받는다"


def test_classify_and_report_get_no_siem_lookup() -> None:
    # 발급할 다음 태스크가 없는 두 태스크다(D-086).
    allowed = shipped()
    for task in ("l2_classify", "l2_report"):
        assert "query_siem" not in allowed[task], task
        assert "count_siem" not in allowed[task], task


def test_the_tasks_that_issue_evidence_can_look_up_siem() -> None:
    allowed = shipped()
    for task in ("l1_alert_triage", "l1_ticket_judgment", "l2_investigate", "l3_verify"):
        assert "query_siem" in allowed[task], task


def test_every_task_name_has_a_key() -> None:
    assert set(TASK_NAMES) == set(shipped())
