"""Agent Log 비밀 값 가림 세 가지(#209). 값은 모두 가짜다."""

import json
from pathlib import Path

import pytest

from soc.agent.redact import REDACTED, build_redactor

CONFIG = {
    "llm": {"api_key_env": "LLM_API_KEY"},
    "tools": {"siem": {"token_env": "SIEM_FAKE_TOKEN"}},
}
ENV = {
    "LLM_API_KEY": "fake-llm-key-aaaa",
    "SIEM_FAKE_TOKEN": "fake-siem-token-bbbb",
    "DATABASE_URL": "postgresql://soc:fake-db-pass-cccc@db.example.com:5432/soc",
    "UNRELATED": "not-a-secret",
}


def redact(value):
    return build_redactor(CONFIG, ENV)(value)


def test_env_values_named_by_config_are_redacted() -> None:
    out = redact({"text": "key fake-llm-key-aaaa and fake-siem-token-bbbb", "x": "not-a-secret"})
    assert out == {"text": f"key {REDACTED} and {REDACTED}", "x": "not-a-secret"}


def test_database_password_is_redacted() -> None:
    out = redact(["fake-db-pass-cccc", "postgresql://u:other-pass-dddd@h/db"])
    assert out[0] == REDACTED
    assert "other-pass-dddd" not in out[1]
    assert out[1].startswith("postgresql://u:")


def test_agent_database_password_is_redacted() -> None:
    # 에이전트 도구의 DB 주소(#211). 비밀번호만 따로 나와도 가린다
    env = {"AGENT_DATABASE_URL": "postgresql://reader:fake-agent-pass-ffff@db.example.com/soc"}
    out = build_redactor(CONFIG, env)({"error": "auth failed for fake-agent-pass-ffff"})
    assert out == {"error": f"auth failed for {REDACTED}"}


def test_secret_shaped_values_are_redacted() -> None:
    cases = {
        "password=fake-eeee next": "password=" + REDACTED + " next",
        "Authorization: Bearer fake-ffff": "Authorization: Bearer " + REDACTED,
        'api_key: "fake-gggg"': 'api_key: "' + REDACTED + '"',
        "API-KEY=fake-hhhh": "API-KEY=" + REDACTED,
    }
    for text, expected in cases.items():
        assert redact(text) == expected


def test_secret_keys_in_objects_are_redacted() -> None:
    out = redact({"password": "fake-iiii", "api_key": "fake-jjjj", "user": "lee.dev"})
    assert out == {"password": REDACTED, "api_key": REDACTED, "user": "lee.dev"}


def test_non_strings_are_kept() -> None:
    assert redact({"n": 3, "b": True, "none": None, "f": 0.5}) == {
        "n": 3,
        "b": True,
        "none": None,
        "f": 0.5,
    }


def test_siem_tool_env_values_are_redacted() -> None:
    # SIEM 도구(#212)의 [tools.siem] url_env·api_key_env.
    # redact.py를 고치지 않고 *_env 규칙으로 잡힌다
    config = {"tools": {"siem": {"url_env": "ELK_URL", "api_key_env": "ELK_API_KEY"}}}
    env = {"ELK_URL": "https://elk.example.com:9200", "ELK_API_KEY": "fake-elk-key-iiii"}
    out = build_redactor(config, env)(
        {"output": "ApiKey fake-elk-key-iiii at https://elk.example.com:9200/logs/_search"}
    )
    assert out == {"output": f"ApiKey {REDACTED} at {REDACTED}/logs/_search"}


MULTILINE_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "ZmFrZS1rZXktbGluZS0xLWZvci10ZXN0cy1vbmx5LWFhYWFhYWFhYWFhYWFhYWFhYWFh\n"
    "ZmFrZS1rZXktbGluZS0yLWZvci10ZXN0cy1vbmx5LWJiYmJiYmJiYmJiYmJiYmJiYmJi\n"
    "-----END OPENSSH PRIVATE KEY-----\n"
)


def test_multiline_secret_is_redacted_whole_escaped_and_partial() -> None:
    # SSH 개인 키(#213)처럼 여러 줄인 값. 통째로 나오면 한 번에, JSON 문자열 속(줄바꿈이 \n
    # 이스케이프)이나 잘려서 일부 줄만 나와도 줄마다 가린다. 한 줄 중간에서 잘린 조각은 못 가린다.
    import json

    cfg = {"tools": {"ssh": {"key_env": "SSH_FAKE_KEY"}}}
    redactor = build_redactor(cfg, {"SSH_FAKE_KEY": MULTILINE_KEY})
    lines = MULTILINE_KEY.splitlines()
    assert redactor({"stdout": MULTILINE_KEY}) == {"stdout": REDACTED}
    escaped = redactor(json.dumps({"stdout": MULTILINE_KEY}))
    partial = redactor("head\n" + lines[1] + "\n" + lines[2][:40])
    for line in lines[1:3]:
        assert line not in escaped
    assert partial == f"head\n{REDACTED}\n" + lines[2][:40]
    assert redactor(lines[2]) == REDACTED


# 모델 입력 가림(#279, D-048)
SAMPLES = json.loads(
    (Path(__file__).parent / "fixtures" / "agent" / "redact_samples.json").read_text(
        encoding="utf-8"
    )
)
ADMIN_ENV = {"LLM_API_KEY": "admin"}  # 흔한 낱말이지만 8자 미만이라 가리지 않는다


def _names(items: list[dict]) -> list[str]:
    return [i["name"] for i in items]


@pytest.mark.parametrize("sample", SAMPLES["kept"], ids=_names(SAMPLES["kept"]))
def test_normal_strings_are_not_changed(sample: dict) -> None:
    redactor = build_redactor(CONFIG, ADMIN_ENV)
    assert redactor(sample["text"]) == sample["text"]
    assert redactor({"x": sample["text"]}) == {"x": sample["text"]}


@pytest.mark.parametrize("sample", SAMPLES["masked"], ids=_names(SAMPLES["masked"]))
def test_secret_shaped_samples_are_masked(sample: dict) -> None:
    out = build_redactor(CONFIG, ADMIN_ENV)(sample["text"])
    secrets = sample["secret"] if isinstance(sample["secret"], list) else [sample["secret"]]
    for secret in secrets:
        assert secret not in out
    for keep in sample["keep"]:
        assert keep in out
    assert REDACTED in out


def test_redaction_is_idempotent() -> None:
    redactor = build_redactor(CONFIG, {**ENV, **ADMIN_ENV})
    texts = [s["text"] for s in SAMPLES["kept"] + SAMPLES["masked"]]
    texts += ["fake-llm-key-aaaa Bearer fake-ffff password=fake-eeee", ENV["DATABASE_URL"]]
    for text in texts:
        once = redactor(text)
        assert redactor(once) == once


def test_env_value_minimum_length_is_eight() -> None:
    config = {"llm": {"api_key_env": "LLM_API_KEY"}}
    assert build_redactor(config, {"LLM_API_KEY": "abc1234"})("key abc1234") == "key abc1234"
    assert build_redactor(config, {"LLM_API_KEY": "abc12345"})("key abc12345") == f"key {REDACTED}"


def test_pwd_value_starting_with_slash_is_skipped_but_other_pwd_values_are_masked() -> None:
    redactor = build_redactor({}, {})
    assert redactor("PWD=/home/alice") == "PWD=/home/alice"
    assert redactor("Pwd=fake-odbc-0005;") == f"Pwd={REDACTED};"
    assert redactor("pwd: fake-pwd-0006") == f"pwd: {REDACTED}"


def test_id_shaped_values_are_never_changed() -> None:
    long_id = "alt_01a19f93-1150-7000-8000-000000000004"
    env = {"LLM_API_KEY": "7000-8000"}  # ID 한가운데 조각과 같은 값
    redactor = build_redactor(CONFIG, env)
    assert redactor(long_id) == long_id
    assert redactor(f'{{"id": "{long_id}", "k": "7000-8000"}}') == (
        f'{{"id": "{long_id}", "k": "{REDACTED}"}}'
    )


def test_secret_keys_in_json_text_match_the_object_key_rule() -> None:
    redactor = build_redactor({}, {})
    value = {"token": "fake-t-0007", "client_secret": "fake-s-0008", "authorization": "Digest x"}
    as_text = json.dumps(value)
    assert redactor(value) == dict.fromkeys(value, REDACTED)
    out = redactor(as_text)
    assert all(v not in out for v in ("fake-t-0007", "fake-s-0008", "Digest x"))


def test_normal_object_keys_are_kept() -> None:
    # 객체 키 규칙은 정확히 같은 이름일 때만 값을 가린다
    value = {"next_token": "cursor-0020", "tokens_in": 120, "token_count": 5, "secretary": "Kim"}
    assert build_redactor({}, {})(value) == value


# 리뷰 반영(#292)
ESCAPE_SECRET = 'pa"ss\\word<9>x한글'


def _json_escaped(secret: str) -> list[str]:
    plain = json.dumps(secret, ensure_ascii=False)[1:-1]
    return [plain, plain.replace("<", "\u003c").replace(">", "\u003e")]


@pytest.mark.parametrize("unit", ["a-", "a_", "ab1-"])
def test_named_secret_scan_time_is_bounded(unit: str) -> None:
    # 이차 시간이던 규칙(프로브: "a-"*16000이 12.6초). 넉넉한 상한만 둔다
    import time

    text = unit * (32_000 // len(unit))
    redactor = build_redactor({}, {})
    started = time.perf_counter()
    assert redactor(text) == text
    assert time.perf_counter() - started < 5.0


def test_long_prefix_before_token_is_still_masked() -> None:
    redactor = build_redactor({}, {})
    assert redactor("my_very_long_prefixword_for_the_app_token=fake-0013") == (
        f"my_very_long_prefixword_for_the_app_token={REDACTED}"
    )
    assert redactor("a-b-c-d-e-f-secret: fake-0014") == f"a-b-c-d-e-f-secret: {REDACTED}"


def test_env_value_is_masked_in_json_escaped_text() -> None:
    # 모델에게 가는 도구 결과는 JSON 문자열(", \, <, >가 이스케이프됨)이다. 파싱이 안 되는
    # 글(잘린 결과 등)에서도 이스케이프된 값을 가려야 한다
    redactor = build_redactor({"x": {"k_env": "K"}}, {"K": ESCAPE_SECRET})
    broken = '<tool_result>\n{"note": "leak ' + _json_escaped(ESCAPE_SECRET)[1] + " end"
    out = redactor(broken)
    for variant in [ESCAPE_SECRET, *_json_escaped(ESCAPE_SECRET)]:
        assert variant not in out
    assert out.endswith(f"leak {REDACTED} end")


def test_pwd_rule_skips_only_two_level_paths() -> None:
    redactor = build_redactor({}, {})
    assert redactor("pwd=/Secret99") == f"pwd={REDACTED}"
    assert redactor("PWD=/home/alice ; USER=root") == "PWD=/home/alice ; USER=root"
    assert redactor('PWD="/var/log/nginx"') == 'PWD="/var/log/nginx"'
    assert redactor("PWD=/a/b") == "PWD=/a/b"  # 한계: /a/b 모양 비밀번호는 못 가린다
    assert redactor("pwd=/") == f"pwd={REDACTED}"


def test_id_shaped_value_is_exempt_only_from_env_value_replacement() -> None:
    long_id = "alt_01a19f93-1150-7000-8000-000000000004"
    redactor = build_redactor(CONFIG, {"LLM_API_KEY": "7000-8000"})
    assert redactor(f'{{"id": "{long_id}"}}') == f'{{"id": "{long_id}"}}'
    assert redactor(f"token={long_id}") == f"token={REDACTED}"  # 키-값 규칙은 면제하지 않는다


@pytest.mark.parametrize("value", [(1, 2), {1, 2}, b"x", object()])
def test_unknown_types_raise_instead_of_passing_through(value: object) -> None:
    redactor = build_redactor({}, {})
    with pytest.raises(TypeError):
        redactor({"a": value})
    with pytest.raises(TypeError):
        redactor([value])


def test_tool_result_envelope_with_object_and_non_string_secret_values() -> None:
    redactor = build_redactor({}, {})
    text = (
        '<tool_result>\n{"call_id": "agl_01a19f93-1266-7000-8000-000000000001", "records": '
        '[{"authorization": {"user": "alice-obj", "pw": "zzz"}, "token": 12345678, '
        '"secret": ["a", "b"], "ok": "fine"}]}\n</tool_result>'
    )
    out = redactor(text)
    body = json.loads(out.split("\n", 1)[1].rsplit("\n", 1)[0])  # 여전히 파싱된다
    record = body["records"][0]
    assert record == {
        "authorization": REDACTED,
        "token": REDACTED,
        "secret": REDACTED,
        "ok": "fine",
    }
    assert body["call_id"] == "agl_01a19f93-1266-7000-8000-000000000001"


def test_unchanged_envelope_text_is_returned_as_is() -> None:
    text = '<tool_result>\n{"records": [{"m": "a \u003cb\u003e 한글", "n": 1}]}\n</tool_result>'
    assert build_redactor({}, {})(text) == text


def test_unparseable_envelope_falls_back_to_text_rules() -> None:
    text = '<tool_result>\n{"records": [{"m": "password=fake-0015", "cut": "ab…'
    out = build_redactor({}, {})(text)
    assert "fake-0015" not in out and out.startswith("<tool_result>")


# 마무리 점검(#292): 모든 정규식의 시간, 실제 봉투 모양
ADVERSARIAL_UNITS = [
    "a.",
    "a:",
    "a://",
    "://",
    "a:b@",
    "http://u:",
    'a" ',
    '" ',
    '":"',
    '\\"',
    " : ",
    "password ",
    "Bearer ",
    "pwd=",
    "token=",
    '"token": ',
    "Authorization: ",
    "alt_",
    "0a1b2c3d-",
]


@pytest.mark.parametrize("unit", ADVERSARIAL_UNITS)
def test_every_rule_stays_fast_on_repeated_input(unit: str) -> None:
    # 모든 규칙(URL 비밀번호, 키-값, Bearer, token·secret, JSON 키, 봉투, ID)을 한 번에 지나가는
    # 평문과 봉투 입력. 재 보니 최악이 0.1초 아래였다. 상한은 느린 CI를 위해 넉넉히 잡는다
    import time

    redactor = build_redactor({"a": {"k_env": "K"}}, {"K": ESCAPE_SECRET})
    plain = (unit * (32_000 // len(unit) + 1))[:32_000]
    body = json.dumps({"call_id": "agl_x", "records": [{"v": plain}]}, ensure_ascii=False)
    for text in (plain, f"<tool_result>\n{body}\n</tool_result>", "<t>\n" + plain):
        started = time.perf_counter()
        redactor(text)
        assert time.perf_counter() - started < 5.0


def test_envelope_is_the_real_registry_and_wrap_data_output() -> None:
    # 손으로 쓴 문자열이 아니라 실제 직렬화 출력으로 확인한다. 태그나 직렬화 모양이 바뀌면
    # _ENVELOPE이 맞지 않아 여기서 실패해야 한다(redact._ENVELOPE·_envelope도 같이 고칠 것)
    from soc.agent.redact import _ENVELOPE
    from soc.agent.runner import wrap_data
    from soc.tools.registry import _dump, _wrap

    secret = {
        "authorization": {"scheme": "Digest", "credentials": "fake-digest-0020"},
        "token": 12345678,
        "secret": ["fake-list-0021"],
        "note": "a <b> & 한글",
        "ok": "fine",
    }
    clean = {"note": "a <b> & 한글", "n": 3}
    redactor = build_redactor({}, {})
    call_id = "agl_01a19f93-1266-7000-8000-000000000001"
    real = {
        "tool_result": _wrap(_dump({"call_id": call_id, "records": [secret]})),
        "data": wrap_data({"alert": secret}),
    }
    for tag, text in real.items():
        match = _ENVELOPE.fullmatch(text)
        assert match is not None and match["tag"] == tag
        out = redactor(text)
        for leaked in ("fake-digest-0020", "12345678", "fake-list-0021"):
            assert leaked not in out
        body = json.loads(_ENVELOPE.fullmatch(out)["body"])  # 봉투가 그대로 풀린다
        assert "fine" in json.dumps(body) and REDACTED in json.dumps(body)
    for text in (_wrap(_dump({"call_id": call_id, "records": [clean]})), wrap_data(clean)):
        assert _ENVELOPE.fullmatch(text) is not None
        assert redactor(text) == text  # 가릴 것이 없으면 원문 그대로
