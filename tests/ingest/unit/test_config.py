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
