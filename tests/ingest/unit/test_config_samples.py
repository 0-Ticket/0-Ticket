"""손으로 만든 local.toml 샘플로 실제 TOML 파싱부터 class 처리까지 확인한다(#340, D-067).

default.toml을 임시 폴더에 복사하고 샘플을 local.toml로 덮어써서 load_config → read_settings를
그대로 거친다. TOML 타입(문자열·정수)이 그대로 검사에 닿는지 보는 것이 목적이다.
"""

import shutil
from pathlib import Path

import pytest

from soc.ingest.config import ConfigError, load_config, read_settings

REPO_CONFIG = Path(__file__).resolve().parents[3] / "config"
SAMPLES = Path(__file__).resolve().parents[2] / "fixtures" / "ingest" / "config"


def settings_from(sample: str, tmp_path: Path):
    shutil.copy(REPO_CONFIG / "default.toml", tmp_path / "default.toml")
    shutil.copy(SAMPLES / sample, tmp_path / "local.toml")
    return read_settings(load_config(tmp_path)["ingest"])


def test_valid_class_sample_reads_without_warnings(tmp_path: Path) -> None:
    settings = settings_from("local_valid_class.toml", tmp_path)
    assert [(s.kind, s.ocsf_class) for s in settings.sources] == [
        ("alert", None),
        ("event", 4002),
        ("event", None),
    ]
    assert settings.warnings == ()


def test_toml_string_class_falls_back_to_base_event(tmp_path: Path) -> None:
    settings = settings_from("local_string_class.toml", tmp_path)
    assert [s.ocsf_class for s in settings.sources] == [0]
    assert len(settings.warnings) == 1
    assert "정수가 아니라" in settings.warnings[0] and "str" in settings.warnings[0]


def test_alert_class_is_ignored_and_a_typo_key_is_reported(tmp_path: Path) -> None:
    settings = settings_from("local_alert_class_and_typo.toml", tmp_path)
    assert [s.ocsf_class for s in settings.sources] == [None, None]
    assert len(settings.warnings) == 2
    assert "이벤트 대상에만" in settings.warnings[0]
    assert "'calss'" in settings.warnings[1]


def test_event_class_2004_falls_back_to_base_event(tmp_path: Path) -> None:
    settings = settings_from("local_alert_class_event_2004.toml", tmp_path)
    assert [s.ocsf_class for s in settings.sources] == [0]
    assert "알럿 전용" in settings.warnings[0]


def test_missing_key_is_still_a_config_error(tmp_path: Path) -> None:
    """수집에 꼭 필요한 값이 없으면 멈춘다. class 처리는 이 규칙을 바꾸지 않는다."""
    with pytest.raises(ConfigError, match=r"sources\[0\]"):
        settings_from("local_missing_key.toml", tmp_path)
