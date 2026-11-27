"""모델이 인용한 siem_ref 검증(#382). 가짜 모델과 가짜 도구로 돈다(ELK·DB 없음).

siem_ref는 밖에서 온 문자열이고 그 값이 ELK 요청 경로를 만든다(`docs/security.md` "밖에서 온
문자열"). 그래서 그 run의 도구 결과에 실제로 보인 ref만 받고, 없는 값을 인용하면 run을 멈춘다.
워커는 통과한 ref의 (_index, _id)를 AgentResult에서 받아 원문을 가져온다.
"""

from typing import Any

from fake_model import FakeModel
from test_agent_core import ALERT_ID, CONFIG, make_task, no_sleep
from test_tools_registry import spec, tool_call, verdict

from soc.agent.agent_log import MemoryLogSink
from soc.agent.runner import run_task
from soc.ids import siem_ref_key
from soc.tools import ToolRegistry

INDEX = ".ds-logs-nginx.access-default-2026.11.04-000001"
DOC_A, DOC_B = "aaa1", "bbb2"
REF_A = siem_ref_key(f"{INDEX}/{DOC_A}")
REF_B = siem_ref_key(f"{INDEX}/{DOC_B}")
UNSEEN = siem_ref_key(f"{INDEX}/never-shown")


def fake_search(args: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """query_siem처럼 히트를 보이고 (_index, _id)를 ctx에 적는 가짜 도구."""
    ctx.siem_docs.update({REF_A: (INDEX, DOC_A), REF_B: (INDEX, DOC_B)})
    return {"hits": [{"siem_ref": REF_A}, {"siem_ref": REF_B}]}


REGISTRY = ToolRegistry([spec("fake_search", fake_search, result_kind="aggregate")])


def config(chars: int = 6_000) -> dict[str, Any]:
    agent = {**CONFIG["agent"], "l1": {**CONFIG["agent"]["l1"], "max_tool_result_chars": chars}}
    agent["l1"]["max_turns"] = 6
    tools = {**CONFIG["tools"], "allowed": {**CONFIG["tools"]["allowed"], "l1": ["fake_search"]}}
    return {**CONFIG, "agent": agent, "tools": tools}


def verdict_with_refs(*refs: str) -> dict[str, Any]:
    return {**verdict(ALERT_ID), "siem_refs": list(refs)}


def run(steps: list[dict[str, Any]], *, cited_refs: Any = None):
    # L1 판정 모델의 출력 계약은 저장하는 Verdict에 siem_refs를 더한 l1_verdict다(#382).
    values: dict[str, Any] = {"output_contract": "l1_verdict"}
    if cited_refs is not None:
        values["cited_refs"] = cited_refs
    task = make_task(**values)
    return run_task(
        task,
        model=FakeModel({"steps": steps}),
        model_name="fake-model",
        log_sink=MemoryLogSink(),
        config=config(),
        registry=REGISTRY,
        sleep=no_sleep,
    )


def refs_from(output: Any) -> list[str]:
    return output.get("siem_refs", [])


def test_a_shown_ref_passes_and_carries_its_index_and_id() -> None:
    steps = [tool_call("fake_search", {}), {"final": verdict_with_refs(REF_A)}]
    result = run(steps, cited_refs=refs_from)

    assert result.ok, result.detail
    assert result.cited_siem_refs == {REF_A: (INDEX, DOC_A)}


def test_two_shown_refs_both_come_back() -> None:
    steps = [tool_call("fake_search", {}), {"final": verdict_with_refs(REF_A, REF_B)}]
    result = run(steps, cited_refs=refs_from)

    assert result.cited_siem_refs == {REF_A: (INDEX, DOC_A), REF_B: (INDEX, DOC_B)}


def test_a_ref_the_tools_never_showed_stops_the_run() -> None:
    steps = [tool_call("fake_search", {}), {"final": verdict_with_refs(UNSEEN)}]
    result = run(steps, cited_refs=refs_from)

    assert not result.ok
    assert result.failure == "evidence_id_error"
    assert result.cited_siem_refs == {}


def test_a_ref_cited_without_calling_any_tool_stops_the_run() -> None:
    result = run([{"final": verdict_with_refs(REF_A)}], cited_refs=refs_from)

    assert result.failure == "evidence_id_error"


def test_a_task_without_cited_refs_is_not_checked_and_gets_an_empty_map() -> None:
    # l2_report처럼 발급하지 않는 태스크는 siem_refs를 쓰지 않는다.
    steps = [tool_call("fake_search", {}), {"final": verdict_with_refs(UNSEEN)}]
    result = run(steps)

    assert result.ok, result.detail
    assert result.cited_siem_refs == {}


def test_citing_no_ref_is_fine() -> None:
    steps = [tool_call("fake_search", {}), {"final": verdict_with_refs()}]
    result = run(steps, cited_refs=refs_from)

    assert result.ok, result.detail
    assert result.cited_siem_refs == {}
