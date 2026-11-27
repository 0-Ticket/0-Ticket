"""발급 근거 발췌의 값 길이와 입력 예산 맞춤을 확인한다(#382, DB 없음).

DB를 쓰는 통째 흐름(발급 → 보고 입력 → 인용 → Artifact)은 test_l2_report_evidence_db.py가 본다.
"""

import copy
import json
from typing import Any

from fake_model import FakeModel
from test_l2_branch_db import analysis_outputs, load_sample

from soc.agent import AgentTask, first_call_size
from soc.agent.agent_log import MemoryLogSink
from soc.agent.config import load_config
from soc.agent.runner import run_task
from soc.evidence.excerpt import (
    MAX_ITEMS,
    MAX_LONG_VALUE_CHARS,
    MAX_TOTAL_CHARS,
    MAX_VALUE_CHARS,
    RESERVE_CHARS,
    _fields,
    fit_to_budget,
)
from soc.l2.analyze.tasks import make_report_task

CONFIG = load_config()
BIG = "x" * 5000


def original(source: dict[str, Any]) -> str:
    return json.dumps({"_index": "i", "_id": "d", "_source": source})


def excerpt(n: int) -> dict[str, Any]:
    """값이 모두 상한까지 찬 발췌 한 건."""
    return {
        "evidence_id": f"evt_01a19f93-1150-7000-8000-{n:012d}",
        "siem_ref": f"i/{n}",
        "time": "2026-11-04T01:02:03+00:00",
        "fields": {"url.path": "p" * MAX_LONG_VALUE_CHARS, "message": "m" * MAX_LONG_VALUE_CHARS},
    }


def builder(sample: dict[str, Any], total: int):
    findings, _ = analysis_outputs(sample)

    def build(shown: list[dict[str, Any]]) -> AgentTask:
        return make_report_task(
            sample["incidents"][0]["id"],
            attempt=1,
            findings=findings,
            incident={"id": sample["incidents"][0]["id"], "summary": "요약"},
            assets=[],
            previous_artifact=None,
            asset_lookup_failed=False,
            context_evidence=(sample["events"][0]["id"], sample["alerts"][0]["id"]),
            issued_evidence_ids=tuple(item["evidence_id"] for item in shown),
            evidence=shown,
            evidence_omitted=total - len(shown),
        )

    return build


def test_long_fields_keep_300_chars_and_the_rest_120() -> None:
    fields, cut = _fields(
        original(
            {
                "url": {"path": BIG, "query": BIG},
                "message": BIG,
                "user_agent": {"original": BIG},
                "user": {"name": BIG},
                "host.name": BIG,
                "http": {"response": {"status_code": 403}},
            }
        )
    )

    for name in ("url.path", "url.query", "message", "user_agent.original"):
        assert len(fields[name]) == MAX_LONG_VALUE_CHARS
    for name in ("user.name", "host.name"):
        assert len(fields[name]) == MAX_VALUE_CHARS
    assert fields["http.response.status_code"] == 403  # 숫자는 그대로
    assert sorted(cut) == sorted(
        ["url.path", "url.query", "message", "user_agent.original", "user.name", "host.name"]
    )


def test_missing_and_non_ecs_fields_are_not_in_the_excerpt() -> None:
    fields, cut = _fields(original({"event": {"module": "suricata"}, "suricata": {"sig": "S"}}))

    assert fields == {"event.module": "suricata"} and cut == []


def test_an_unreadable_original_gives_no_fields() -> None:
    assert _fields("not json") == ({}, [])


def test_excerpts_stop_at_20_items_and_the_omitted_count_is_the_rest() -> None:
    sample = load_sample()
    items = [excerpt(n) for n in range(30)]

    task = fit_to_budget(items, builder(sample, 30), first_call_size)

    assert len(task.data["evidence"]) == MAX_ITEMS
    assert task.data["evidence_omitted"] == 30 - MAX_ITEMS


def test_the_total_added_stays_within_the_cap_and_leaves_the_reserve() -> None:
    sample = load_sample()
    build = builder(sample, 20)
    items = [excerpt(n) for n in range(20)]
    base, limit = first_call_size(build([]), CONFIG)

    task = fit_to_budget(items, build, first_call_size)

    chars, _ = first_call_size(task, CONFIG)
    assert chars - base <= MAX_TOTAL_CHARS
    assert chars <= limit - RESERVE_CHARS


def test_it_takes_the_most_that_fit_and_never_cuts_one_in_the_middle() -> None:
    sample = load_sample()
    build = builder(sample, 20)
    items = [excerpt(n) for n in range(20)]
    base, _ = first_call_size(build([]), CONFIG)
    config = copy.deepcopy(CONFIG)
    config["agent"]["l2"]["max_input_chars"] = base + RESERVE_CHARS + 3_000  # 몇 건만 들어간다

    def measure(task: AgentTask) -> tuple[int, int]:
        return first_call_size(task, config)

    task = fit_to_budget(items, build, measure)

    shown = task.data["evidence"]
    assert 0 < len(shown) < 20
    assert shown == items[: len(shown)]  # 앞에서부터, 한 건은 통째로
    assert task.data["evidence_omitted"] == 20 - len(shown)
    chars, limit = measure(task)
    assert chars <= limit - RESERVE_CHARS
    # 한 건을 더 실으면 넘는다(최대한 싣는다)
    assert measure(build(items[: len(shown) + 1]))[0] - base > limit - base - RESERVE_CHARS


def test_no_room_sends_no_excerpt_and_only_the_count() -> None:
    sample = load_sample()
    build = builder(sample, 5)
    items = [excerpt(n) for n in range(5)]
    base, _ = first_call_size(build([]), CONFIG)
    config = copy.deepcopy(CONFIG)
    config["agent"]["l2"]["max_input_chars"] = base + RESERVE_CHARS  # 남은 예산 0

    task = fit_to_budget(items, build, lambda t: first_call_size(t, config))

    assert task.data["evidence"] == [] and task.data["evidence_omitted"] == 5


def test_when_the_input_is_over_the_limit_without_excerpts_it_is_left_as_it_was() -> None:
    sample = load_sample()
    build = builder(sample, 3)
    config = copy.deepcopy(CONFIG)
    config["agent"]["l2"]["max_input_chars"] = 100  # 발췌 없이도 넘는다

    task = fit_to_budget(
        [excerpt(n) for n in range(3)], build, lambda t: first_call_size(t, config)
    )

    assert task.data["evidence"] == [] and task.data["evidence_omitted"] == 3
    # 이 입력은 기존대로 run이 budget_exceeded로 멈춘다(별도 이슈). 발췌가 원인이 아니다
    result = run_with(task, config)
    assert result.failure == "budget_exceeded"


def run_with(task: AgentTask, config: dict[str, Any]) -> Any:
    _, analysis = analysis_outputs(load_sample())
    return run_task(
        task,
        model=FakeModel({"steps": [{"final": analysis}]}),
        model_name="fake-model",
        log_sink=MemoryLogSink(),
        config=config,
    )


def test_adding_the_excerpts_does_not_cause_a_new_budget_exceeded() -> None:
    sample = load_sample()
    build = builder(sample, 20)
    items = [excerpt(n) for n in range(20)]
    base, _ = first_call_size(build([]), CONFIG)
    config = copy.deepcopy(CONFIG)
    # 발췌 없이는 들어가는 한도에서, 발췌를 최대한 실은 입력이 실제 run에서도 통과한다
    config["agent"]["l2"]["max_input_chars"] = base + RESERVE_CHARS + 6_000
    without = run_with(build([]), config)
    assert without.ok, without.detail

    task = fit_to_budget(items, build, lambda t: first_call_size(t, config))

    assert task.data["evidence"]  # 실제로 실렸다
    result = run_with(task, config)
    assert result.ok, result.detail  # 발췌를 더해도 입력 예산 안이다
