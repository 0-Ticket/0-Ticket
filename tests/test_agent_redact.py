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
