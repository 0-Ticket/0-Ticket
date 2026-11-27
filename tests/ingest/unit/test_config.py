"""수집 설정 로더(#218): default.toml 위에 local.toml을 덮어쓰고 [ingest]만 돌려준다."""

import re
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
    # 이벤트는 수집하지 않는다(#382, D-085). 알럿 하나뿐이다
    assert [(s.kind, s.key, s.time_field) for s in settings.sources] == [
        ("alert", ".alerts-security.alerts-default", "@timestamp"),
    ]


def test_default_config_declares_no_event_class() -> None:
    """D-067은 폐기됐다(#382). 이벤트 대상이 없으니 선언할 클래스도 없다.

    설정 읽기는 class를 계속 받는다(검사 코드는 남아 있다). 배포 설정이 쓰지 않을 뿐이다.
    """
    settings = read_settings(load_config(REPO_CONFIG)["ingest"])
    assert [(s.key, s.ocsf_class) for s in settings.sources] == [
        (".alerts-security.alerts-default", None),
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
    """배포 설정에 이벤트 대상 하나를 더한 것.

    배포 설정은 이벤트를 수집하지 않지만(#382, D-085) 설정 읽기는 이벤트 대상과 class를
    계속 받는다. 그 검사 코드를 확인하려면 대상을 테스트가 만들어야 한다.
    """
    ingest = load_config(REPO_CONFIG)["ingest"]
    ingest["sources"] = [
        *ingest["sources"],
        {
            "kind": "event",
            "key": "logs-nginx.access-*",
            "time_field": "@timestamp",
            "class": 4002,
        },
    ]
    return ingest


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


BASE_EVENT = 0
NOT_INTEGER = "정수가 아니라"
ALERT_ONLY = "알럿 전용"
NOT_PINNED = "받아 둔 클래스가 아니라"


def class_of(settings, kind: str):
    return [s.ocsf_class for s in settings.sources if s.kind == kind][0]


def test_default_config_has_no_warnings() -> None:
    assert read_settings(valid_ingest()).warnings == ()


@pytest.mark.parametrize("value", [2004, 9999, -1, "4002", 4002.0, True, None])
def test_event_source_with_a_bad_class_falls_back_to_base_event(value) -> None:
    """클래스를 정할 수 없으면 Base Event(0)로 두고 멈추지 않는다. 경고는 남긴다(#340)."""
    ingest = valid_ingest()
    event_source(ingest)["class"] = value
    settings = read_settings(ingest)
    assert class_of(settings, "event") == BASE_EVENT
    assert len(settings.warnings) == 1
    assert re.search(r"sources\[\d+\]\.class", settings.warnings[0])


@pytest.mark.parametrize("value", [2004, 4002, 0])
def test_alert_source_class_is_ignored_with_a_warning(value: int) -> None:
    ingest = valid_ingest()
    ingest["sources"][0]["class"] = value
    settings = read_settings(ingest)
    assert class_of(settings, "alert") is None
    assert len(settings.warnings) == 1
    assert re.search(r"sources\[0\]\.class", settings.warnings[0])


@pytest.mark.parametrize("stray", ["calss", "Class", "classs", "timefield", "kind2", ""])
def test_unknown_source_key_is_ignored_with_a_warning_naming_it(stray: str) -> None:
    """오타 키는 무시하고 멈추지 않되 조용히 사라지지 않게 경고에 키 이름을 담는다."""
    ingest = valid_ingest()
    event_source(ingest)[stray] = 4002
    settings = read_settings(ingest)
    assert class_of(settings, "event") == 4002  # 알려진 키의 값은 그대로 쓴다
    assert len(settings.warnings) == 1
    assert repr(stray) in settings.warnings[0]


def test_source_with_only_known_keys_gives_no_warning() -> None:
    ingest = valid_ingest()
    assert all(
        set(source) <= {"kind", "key", "time_field", "class"} for source in ingest["sources"]
    )
    assert read_settings(ingest).warnings == ()


@pytest.mark.parametrize(
    ("value", "expected", "also"),
    [
        ("4002", NOT_INTEGER, "str"),
        (4002.0, NOT_INTEGER, "float"),
        (True, NOT_INTEGER, "bool"),
        (None, NOT_INTEGER, "NoneType"),
        (2004, ALERT_ONLY, "2004"),
        (9999, NOT_PINNED, "9999"),
        (-1, NOT_PINNED, "-1"),
        (1, NOT_PINNED, "classes/1.json"),
    ],
)
def test_each_class_rule_gives_its_own_warning(value, expected: str, also: str) -> None:
    """규칙마다 다른 경고가 나온다. 한 규칙의 문구가 다른 규칙 위반에 섞이지 않는다."""
    ingest = valid_ingest()
    event_source(ingest)["class"] = value
    (warning,) = read_settings(ingest).warnings
    assert expected in warning
    assert also in warning
    assert "Base Event(0)" in warning
    assert all(other not in warning for other in {NOT_INTEGER, ALERT_ONLY, NOT_PINNED} - {expected})
