"""Agent Log 비밀 값 가림 세 가지(#209). 값은 모두 가짜다."""

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
