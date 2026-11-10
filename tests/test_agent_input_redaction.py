"""모델에게 보내는 입력의 비밀 값 가림(#279, D-048). 값은 모두 가짜다.

가짜 모델이 받은 입력(FakeModel.calls)과 Agent Log 줄을 함께 본다.
"""

import copy
import json
from typing import Any

import pytest
from fake_model import FakeModel
from test_agent_core import ALERT_ID, CONFIG, make_task, no_sleep

from soc.agent.agent_log import MemoryLogSink, jsonable
from soc.agent.runner import run_task
from soc.tools import ToolRegistry, ToolSpec

ENV_SECRET = "FAKE-ENV-SECRET-3333"
DATA_TOKEN = "fake-token-data-0001"
RECORD_PASSWORD = "fake-pass-record-0002"
TEXT_BASIC = "ZmFrZXVzZXI6ZmFrZXBhc3M="
AGG_API_KEY = "fake-key-aggregate-0004"
SECRETS = (ENV_SECRET, DATA_TOKEN, RECORD_PASSWORD, TEXT_BASIC, AGG_API_KEY)

TOOLS = ("leak_records", "leak_text", "leak_aggregate")
LEAK_CONFIG: dict[str, Any] = copy.deepcopy(CONFIG)
LEAK_CONFIG["tools"]["allowed"] = {stage: list(TOOLS) for stage in ("l1", "l2", "l3")}
LEAK_CONFIG["agent"]["l1"]["max_turns"] = 8  # 도구 3개 + 형식 오류 재요청이 들어간다


def _spec(name: str, kind: str, handler: Any, **kwargs: Any) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="테스트용",
        handler=handler,
        bundle="test",
        result_kind=kind,
        **kwargs,
    )  # type: ignore[arg-type]


LEAK_REGISTRY = ToolRegistry(
    [
        _spec(
            "leak_records",
            "records",
            lambda args, ctx: [
                {
                    "id": ALERT_ID,
                    "url.query": f"page=2&password={RECORD_PASSWORD}",
                    "note": f"env {ENV_SECRET}",
                }
            ],
            id_fields=("id",),
        ),
        _spec(
            "leak_text",
            "text",
            lambda args, ctx: f"GET /admin Authorization: Basic {TEXT_BASIC} ok",
        ),
        _spec(
            "leak_aggregate",
            "aggregate",
            lambda args, ctx: {"top": [{"value": f"api_key={AGG_API_KEY}", "count": 3}]},
        ),
    ]
)

LEAK_DATA = {
    "alert": {
        "id": ALERT_ID,
        "title": "Suspicious PowerShell Execution",
        "url": f"/x?token={DATA_TOKEN}&page=1",
    }
}
FINAL = {
    "decision": "benign",
    "confidence": 0.9,
    "reason": "정상",
    "evidence_ids": [ALERT_ID],
}


def scenario(*tool_names: str, final: Any = FINAL) -> dict[str, Any]:
    steps: list[dict[str, Any]] = [{"tool_call": {"name": n, "arguments": {}}} for n in tool_names]
    steps.append({"final": final})
    return {"steps": steps}


def run(
    steps: dict[str, Any],
    *,
    config: dict[str, Any] = LEAK_CONFIG,
    registry: ToolRegistry = LEAK_REGISTRY,
    data: Any = LEAK_DATA,
):
    model = FakeModel(steps)
    sink = MemoryLogSink()
    result = run_task(
        make_task(data=data),
        model=model,
        model_name="fake-model",
        log_sink=sink,
        config=config,
        registry=registry,
        sleep=no_sleep,
    )
    return result, model, sink


def sent_inputs(model: FakeModel) -> list[list[Any]]:
    return [jsonable(call["input"]) for call in model.calls]


def rebuild(rows: list[dict[str, Any]]) -> list[list[Any]]:
    """D-036 복원: model 줄(sent=false 제외)을 seq 순으로 이어 붙인 호출별 전체 입력."""
    out: list[list[Any]] = []
    for row in sorted(rows, key=lambda r: r["seq"]):
        if row["kind"] != "model" or row["details"].get("sent") is False:
            continue
        value = row["input"]
        previous = out[-1] if out else []
        start = value.get("input_from", 0)
        out.append(previous[:start] + value["input"])
    return out


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", ENV_SECRET)


def test_model_input_and_agent_log_have_no_secrets() -> None:
    result, model, sink = run(scenario(*TOOLS))
    assert result.ok is True, result.detail
    assert len(model.calls) == 4
    seen = json.dumps(sent_inputs(model), ensure_ascii=False)
    logged = json.dumps(sink.rows, ensure_ascii=False)
    for secret in SECRETS:
        assert secret not in seen
        assert secret not in logged
    assert "page=2" in seen and "page=1" in seen  # 비밀이 아닌 부분은 남는다
    assert "[REDACTED]" in seen


def test_log_model_rows_rebuild_to_exactly_what_the_model_received() -> None:
    _, model, sink = run(scenario(*TOOLS))
    assert rebuild(sink.rows) == sent_inputs(model)
    assert not any(r["details"].get("input_reset") for r in sink.rows)


def test_records_tool_row_matches_what_the_model_saw() -> None:
    _, model, sink = run(scenario("leak_records"))
    row = next(r for r in sink.rows if r["kind"] == "tool")
    shown = json.loads(model.calls[1]["input"][-1]["output"].split("\n", 1)[1].rsplit("\n", 1)[0])
    assert row["output"]["records"] == shown["records"]


def test_history_is_a_prefix_across_turns_and_format_retry() -> None:
    wrong = {**FINAL, "confidence": 7}
    steps = scenario("leak_records", "leak_text", final=wrong)
    steps["steps"].append({"final": FINAL})
    result, model, sink = run(steps)
    assert result.ok is True, result.detail
    inputs = sent_inputs(model)
    assert len(inputs) == 4
    for earlier, later in zip(inputs, inputs[1:], strict=False):
        assert later[: len(earlier)] == earlier  # 같은 입력 이력은 같은 가림 결과(D-036)
    assert rebuild(sink.rows) == inputs
    assert not any(r["details"].get("input_reset") for r in sink.rows)


def test_redaction_failure_sends_nothing_and_ends_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import soc.agent.runner as runner

    real = runner.build_redactor

    def broken(config: Any, environ: Any = None):
        redact = real(config, environ)

        def redact_or_fail(value: Any) -> Any:
            if isinstance(value, dict) and "role" in value:  # 모델 입력 항목만 실패시킨다
                raise RuntimeError("boom")
            return redact(value)

        return redact_or_fail

    monkeypatch.setattr(runner, "build_redactor", broken)
    result, model, sink = run(scenario())
    assert result.ok is False
    assert result.failure == "provider_error"
    assert model.calls == []  # 원문은 보내지 않았다
    unsent = [r for r in sink.rows if r["details"].get("sent") is False]
    assert len(unsent) == 1
    assert unsent[0]["details"]["failure"] == "provider_error"
    assert DATA_TOKEN not in json.dumps(sink.rows, ensure_ascii=False)


def test_env_value_overlapping_an_id_does_not_change_the_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "7000-8000")  # ALERT_ID의 한가운데 조각이다
    result, model, _ = run(scenario("leak_records"))
    assert result.ok is True, result.detail  # 근거 장부 인용이 통과한다
    assert result.failure is None
    assert ALERT_ID in json.dumps(sent_inputs(model), ensure_ascii=False)
    assert result.cited_evidence_ids == [ALERT_ID]


def test_short_env_value_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "admin")
    data = {"alert": {"id": ALERT_ID, "user.name": "admin", "msg": "login-failed admin"}}
    _, model, _ = run(scenario(), data=data)
    user = model.calls[0]["input"][0]["content"]
    assert "login-failed admin" in user and '"user.name": "admin"' in user


def test_tool_name_and_call_ids_are_not_touched() -> None:
    _, model, _ = run(scenario("leak_text"))
    items = jsonable(model.calls[1]["input"])
    call = next(i for i in items if i.get("type") == "function_call")
    out = next(i for i in items if i.get("type") == "function_call_output")
    assert call["name"] == "leak_text"
    assert call["call_id"] == out["call_id"]
