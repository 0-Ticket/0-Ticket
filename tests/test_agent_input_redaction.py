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
from soc.agent.redact import build_redactor
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
            if isinstance(value, dict) and "content" in value:  # 첫 사용자 메시지 본문만 실패시킨다
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


def test_call_ids_and_tool_names_survive_even_when_they_look_like_the_env_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SDK call_id(call_1_0)와 같은 8자 환경변수 값. 도구 호출·결과의 짝이 깨지면 안 된다.
    # 본문 속 같은 문자열은 가려진다(가림이 켜져 있다는 증거)
    monkeypatch.setenv("LLM_API_KEY", "call_1_0")
    registry = ToolRegistry(
        [_spec("leak_text", "text", lambda args, ctx: "id call_1_0 appears in the text")]
    )
    config = copy.deepcopy(LEAK_CONFIG)
    config["tools"]["allowed"]["l1"] = ["leak_text"]
    steps = {
        "steps": [
            {"tool_calls": [{"name": "leak_text", "arguments": {}}]},
            {"final": FINAL},
        ]
    }
    result, model, _ = run(steps, config=config, registry=registry)
    assert result.ok is True, result.detail
    items = jsonable(model.calls[1]["input"])
    call = next(i for i in items if i.get("type") == "function_call")
    out = next(i for i in items if i.get("type") == "function_call_output")
    assert call["name"] == "leak_text"
    assert call["call_id"] == out["call_id"] == "call_1_0"
    assert "call_1_0" not in out["output"] and "[REDACTED]" in out["output"]


ESCAPE_SECRET = 'pa"ss\\word<9>x한글'


def all_strings(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(all_strings(v) for v in value.values())
    if isinstance(value, list):
        return "\n".join(all_strings(v) for v in value)
    return ""


def test_env_secret_with_json_special_characters_is_masked_in_model_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", ESCAPE_SECRET)
    note = f"env {ESCAPE_SECRET} end"
    registry = ToolRegistry(
        [
            _spec(
                "leak_records",
                "records",
                lambda a, c: [{"id": ALERT_ID, "note": note}],
                id_fields=("id",),
            ),
            _spec("leak_text", "text", lambda a, c: note),
        ]
    )
    config = copy.deepcopy(LEAK_CONFIG)
    config["tools"]["allowed"]["l1"] = ["leak_records", "leak_text"]
    data = {"alert": {"id": ALERT_ID, "note": note}}
    result, model, sink = run(
        scenario("leak_records", "leak_text"), config=config, registry=registry, data=data
    )
    assert result.ok is True, result.detail
    plain = json.dumps(ESCAPE_SECRET, ensure_ascii=False)[1:-1]
    variants = [ESCAPE_SECRET, plain, plain.replace("<", "\\u003c").replace(">", "\\u003e")]
    seen = all_strings(sent_inputs(model))
    logged = json.dumps(sink.rows, ensure_ascii=False)
    for variant in variants:
        assert variant not in seen
        assert variant not in logged
    assert rebuild(sink.rows) == sent_inputs(model)


def test_object_and_non_string_values_under_secret_keys_are_masked_in_model_input() -> None:
    record = {
        "id": ALERT_ID,
        "authorization": {"scheme": "Digest", "credentials": "fake-digest-obj-0010"},
        "token": 12345678,
        "secret": ["fake-list-0011"],
        "title": "kept",
    }
    registry = ToolRegistry(
        [_spec("leak_records", "records", lambda a, c: [record], id_fields=("id",))]
    )
    config = copy.deepcopy(LEAK_CONFIG)
    config["tools"]["allowed"]["l1"] = ["leak_records"]
    data = {
        "alert": {"id": ALERT_ID, "token": 87654321, "meta": {"secret": {"k": "fake-data-0012"}}}
    }
    _, model, sink = run(scenario("leak_records"), config=config, registry=registry, data=data)
    seen = all_strings(sent_inputs(model))
    for leaked in (
        "fake-digest-obj-0010",
        "12345678",
        "fake-list-0011",
        "87654321",
        "fake-data-0012",
    ):
        assert leaked not in seen
    assert "kept" in seen
    assert rebuild(sink.rows) == sent_inputs(model)
    row = next(r for r in sink.rows if r["kind"] == "tool")
    text = jsonable(model.calls[1]["input"])[-1]["output"]
    body = json.loads(text.split("\n", 1)[1].rsplit("\n", 1)[0])
    assert body["records"] == row["output"]["records"]


def test_model_text_is_unchanged_when_nothing_is_masked() -> None:
    from soc.tools.registry import _dump, _wrap

    registry = ToolRegistry(
        [
            _spec(
                "leak_records",
                "records",
                lambda a, c: [{"id": ALERT_ID, "note": "a <b> & é 한글", "n": 3}],
                id_fields=("id",),
            )
        ]
    )
    config = copy.deepcopy(LEAK_CONFIG)
    config["tools"]["allowed"]["l1"] = ["leak_records"]
    _, model, sink = run(scenario("leak_records"), config=config, registry=registry)
    row = next(r for r in sink.rows if r["kind"] == "tool")
    sent = jsonable(model.calls[1]["input"])[-1]["output"]
    assert sent == _wrap(_dump(row["output"]))  # 원문 그대로(이스케이프·한글 포함)


def test_redaction_failure_on_the_second_call_stops_before_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import soc.agent.runner as runner

    real = runner.build_redactor

    def broken(config: Any, environ: Any = None):
        redact = real(config, environ)

        def redact_or_fail(value: Any) -> Any:
            if isinstance(value, dict) and "output" in value:  # 도구 결과 항목 본문만 실패시킨다
                raise RuntimeError("boom")
            return redact(value)

        return redact_or_fail

    monkeypatch.setattr(runner, "build_redactor", broken)
    result, model, sink = run(scenario("leak_records"))
    assert result.failure == "provider_error"
    assert len(model.calls) == 1  # 도구 결과가 든 두 번째 입력은 보내지 않았다
    assert RECORD_PASSWORD not in json.dumps(sent_inputs(model), ensure_ascii=False)
    assert RECORD_PASSWORD not in json.dumps(sink.rows, ensure_ascii=False)
    assert [r for r in sink.rows if r["details"].get("sent") is False]


def test_redactor_setup_failure_is_reported_apart_from_agent_log_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import soc.agent.runner as runner

    real = runner.build_redactor

    def broken(config: Any, environ: Any = None):
        if "agent" in config:  # _before_start의 빈 설정 대체 경로는 통과시킨다
            raise RuntimeError("boom")
        return real(config, environ)

    monkeypatch.setattr(runner, "build_redactor", broken)
    result, model, sink = run(scenario())
    assert result.failure == "provider_error"
    assert "Agent Log 설정" not in (result.detail or "")
    assert "가림" in (result.detail or "")
    assert model.calls == []
    assert [r for r in sink.rows if r["details"].get("sent") is False]


def test_without_the_filter_the_model_would_receive_the_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 대조: 가림 함수가 아무것도 가리지 않으면 같은 시나리오에서 비밀이 모델 입력에 그대로 있다.
    # 위 테스트들이 SDK 필터 경로를 실제로 거친다는 증거다
    import soc.agent.runner as runner

    monkeypatch.setattr(runner, "build_redactor", lambda config, environ=None: lambda value: value)
    _, model, _ = run(scenario(*TOOLS))
    seen = json.dumps(sent_inputs(model), ensure_ascii=False)
    for secret in SECRETS:
        assert secret in seen


def test_normal_fields_reach_the_model_unchanged() -> None:
    registry = ToolRegistry(
        [
            _spec(
                "leak_records",
                "records",
                lambda args, ctx: [
                    {
                        "id": ALERT_ID,
                        "next_token": "cursor-0020",
                        "tokens_in": 120,
                        "msg": "sudo: alice : PWD=/home/alice ; USER=root",
                    }
                ],
                id_fields=("id",),
            )
        ]
    )
    config = copy.deepcopy(LEAK_CONFIG)
    config["tools"]["allowed"]["l1"] = ["leak_records"]
    _, model, _ = run(scenario("leak_records"), config=config, registry=registry)
    seen = json.dumps(sent_inputs(model), ensure_ascii=False)
    for kept in ("cursor-0020", '\\"tokens_in\\": 120', "PWD=/home/alice"):
        assert kept in seen


def test_sdk_input_items_are_dicts_and_objects_are_converted_not_leaked() -> None:
    # SDK(openai-agents 0.24.0)는 모델 입력 항목을 모두 dict로 만들어 필터에 넘긴다(to_input_item이
    # model_dump로 바꾼다). 객체가 오지 않으므로 이 경로는 테스트로 고정할 수 없고, _as_json은 SDK가
    # 바뀌어 객체가 와도 가림을 건너뛰지 않게 하는 방어다
    from agents.testing import function_call

    from soc.agent.redact import build_redactor
    from soc.agent.runner import _as_json

    _, model, _ = run(scenario("leak_records"))
    assert all(isinstance(item, dict) for call in model.calls for item in call["input"])
    obj = function_call(
        "leak_text", json.dumps({"note": "password=fake-pass-obj-0009"}), call_id="call_obj"
    )
    assert not isinstance(obj, dict)
    out = build_redactor({}, {})(_as_json(obj))
    assert isinstance(out, dict)
    assert "fake-pass-obj-0009" not in json.dumps(out)


def test_structural_key_exemption_applies_only_to_top_level_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 최상위 type·role·call_id·id·name·status만 그대로 둔다. 중첩 값과 content·arguments·output
    # 안의 같은 이름 키는 계속 가린다
    from soc.agent.runner import _screen_item

    monkeypatch.setenv("LLM_API_KEY", "call_1_0")
    redact = build_redactor(LEAK_CONFIG, {"LLM_API_KEY": "call_1_0"})
    item = {
        "type": "function_call_output",
        "call_id": "call_1_0",
        "id": "call_1_0",
        "name": "call_1_0",
        "status": "call_1_0",
        "role": "call_1_0",
        "output": "<tool_result>\n"
        + json.dumps({"records": [{"call_id": "call_1_0", "name": "call_1_0", "id": "call_1_0"}]})
        + "\n</tool_result>",
        "content": [
            {"type": "input_text", "text": "call_1_0", "name": "call_1_0", "id": "call_1_0"},
        ],
        "arguments": json.dumps({"call_id": "call_1_0", "name": "password=fake-name-0030"}),
    }
    out = _screen_item(item, redact)
    for key in ("type", "call_id", "id", "name", "status", "role"):
        assert out[key] == item[key]  # 최상위는 그대로(call_id 등은 환경변수 값과 같은 값이다)
    assert list(out) == list(item)  # 키 순서도 그대로
    nested = json.dumps([out["output"], out["content"], out["arguments"]], ensure_ascii=False)
    assert "call_1_0" not in nested  # 중첩 값은 가려진다
    assert "fake-name-0030" not in nested
    assert nested.count("[REDACTED]") >= 8


def test_structural_key_exemption_does_not_cover_non_structural_top_level_keys() -> None:
    from soc.agent.runner import _screen_item

    redact = build_redactor({}, {})
    item = {"role": "user", "content": "password=fake-pass-0031", "extra": "token=fake-0032"}
    out = _screen_item(item, redact)
    assert out["role"] == "user"
    assert "fake-pass-0031" not in out["content"] and "fake-0032" not in out["extra"]
