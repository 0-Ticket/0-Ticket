"""수집 설정 로더(#218): default.toml 위에 local.toml을 덮어쓰고 [ingest]만 돌려준다."""

from pathlib import Path

import pytest

from soc.ingest.config import ConfigError, load_config, read_settings

REPO_CONFIG = Path(__file__).resolve().parents[3] / "config"


def test_default_config_reads_into_settings() -> None:
    config = load_config(REPO_CONFIG)
    assert set(config) == {"ingest"}
    settings = read_settings(config["ingest"])
    assert settings.siem_profile == "elk-default"
    assert (settings.url_env, settings.api_key_env) == ("ELK_URL", "ELK_API_KEY")
    assert settings.page_size == 500
    assert [(s.kind, s.key, s.time_field) for s in settings.sources] == [
        ("alert", ".alerts-security.alerts-default", "@timestamp"),
        ("event", "logs-nginx.access-*", "@timestamp"),
        ("event", "logs-apache.access-*", "@timestamp"),
        ("event", "logs-aws.cloudtrail-*", "@timestamp"),
        ("event", "logs-azure.activitylogs-*", "@timestamp"),
        ("event", "logs-gcp.audit-*", "@timestamp"),
    ]


def test_default_config_declares_the_event_class_of_web_sources_only() -> None:
    """class는 선택이고(#340, D-065), 지금은 샘플로 확인한 nginx·apache만 적는다."""
    settings = read_settings(load_config(REPO_CONFIG)["ingest"])
    assert [(s.key, s.ocsf_class) for s in settings.sources] == [
        (".alerts-security.alerts-default", None),
        ("logs-nginx.access-*", 4002),
        ("logs-apache.access-*", 4002),
        ("logs-aws.cloudtrail-*", None),
        ("logs-azure.activitylogs-*", None),
        ("logs-gcp.audit-*", None),
    ]


def test_local_overrides_default_and_only_ingest_is_returned(tmp_path: Path) -> None:
    (tmp_path / "default.toml").write_text(
        '[llm]\nmodel = "a"\n[ingest]\nsiem_profile = "elk-default"\npage_size = 500\n',
        encoding="utf-8",
    )
    (tmp_path / "local.toml").write_text("[ingest]\npage_size = 50\n", encoding="utf-8")
    assert load_config(tmp_path) == {"ingest": {"siem_profile": "elk-default", "page_size": 50}}


def test_missing_ingest_section_gives_empty(tmp_path: Path) -> None:
    (tmp_path / "default.toml").write_text('[llm]\nmodel = "a"\n', encoding="utf-8")
    assert load_config(tmp_path) == {"ingest": {}}


def valid_ingest() -> dict:
    return load_config(REPO_CONFIG)["ingest"]


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c.pop("siem_profile"),
        lambda c: c.update(url_env=""),
        lambda c: c.update(api_key_env=None),
        lambda c: c.update(page_size=0),
        lambda c: c.update(page_size=10_001),  # ELK의 기본 max_result_window
        lambda c: c.update(page_size=True),
        lambda c: c.update(max_bytes="5MB"),
        lambda c: c.pop("deadline_seconds"),
        lambda c: c.update(sources=[]),
        lambda c: c["sources"][0].update(kind="incident"),
        lambda c: c["sources"][0].update(key=""),
        lambda c: c["sources"][0].update(key="logs-*/_delete_by_query"),
        lambda c: c["sources"][0].update(key="logs-*?x=1"),
        lambda c: c["sources"][0].update(key="_all"),
        lambda c: c["sources"][0].update(time_field="a b"),
        lambda c: c["sources"].append(dict(c["sources"][0])),
    ],
)
def test_bad_settings_are_rejected(change) -> None:
    ingest = valid_ingest()
    change(ingest)
    with pytest.raises(ConfigError):
        read_settings(ingest)


def event_source(ingest: dict) -> dict:
    return next(s for s in ingest["sources"] if s["kind"] == "event")


@pytest.mark.parametrize("uid", [0, 2003, 3002, 4001, 4002, 4003, 6003])
def test_event_source_accepts_every_pinned_class_except_2004(uid: int) -> None:
    ingest = valid_ingest()
    event_source(ingest)["class"] = uid
    settings = read_settings(ingest)
    assert [s.ocsf_class for s in settings.sources if s.kind == "event"][0] == uid


def test_event_source_without_class_keeps_none() -> None:
    ingest = valid_ingest()
    event_source(ingest).pop("class", None)
    assert [s.ocsf_class for s in read_settings(ingest).sources if s.kind == "event"][0] is None


@pytest.mark.parametrize(
    "value",
    [
        2004,  # 알럿 전용 클래스
        9999,  # 정의 파일이 없는 번호
        -1,
        "4002",
        4002.0,
        True,  # bool은 정수가 아니다
        None,
    ],
)
def test_event_source_rejects_a_bad_class(value) -> None:
    ingest = valid_ingest()
    event_source(ingest)["class"] = value
    with pytest.raises(ConfigError, match=r"sources\[\d+\]\.class"):
        read_settings(ingest)


@pytest.mark.parametrize("value", [2004, 4002, 0])
def test_alert_source_rejects_class(value: int) -> None:
    ingest = valid_ingest()
    ingest["sources"][0]["class"] = value
    with pytest.raises(ConfigError, match=r"sources\[0\]\.class"):
        read_settings(ingest)
