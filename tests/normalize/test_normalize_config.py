"""정규화 설정 로더가 기본값을 읽고 틀린 값을 거부하는지 확인한다."""

from pathlib import Path

import pytest

from soc.normalize.config import ConfigError, load_settings


def write_config(directory: Path, body: str) -> Path:
    """default.toml을 쓰고 그 폴더를 돌려준다.

    Args:
        directory: 쓸 폴더.
        body: 파일 내용.
    """
    (directory / "default.toml").write_text(body, encoding="utf-8")
    return directory


VALID = """
[normalize]
batch_size = 10
lease_seconds = 60
connect_timeout_seconds = 3

[asset_lookup]
statement_timeout_ms = 1000
"""


def test_default_settings_are_read(default_config_dir: Path) -> None:
    settings = load_settings(default_config_dir)

    assert (settings.batch_size, settings.lease_seconds) == (200, 600)
    assert settings.connect_timeout_seconds == 5
    assert settings.asset_statement_timeout_ms == 5000


def test_local_file_overrides_default(tmp_path: Path) -> None:
    write_config(tmp_path, VALID)
    (tmp_path / "local.toml").write_text("[normalize]\nbatch_size = 20\n", encoding="utf-8")

    settings = load_settings(tmp_path)

    assert (settings.batch_size, settings.lease_seconds) == (20, 60)


@pytest.mark.parametrize(
    "old, new",
    [
        ("batch_size = 10", "batch_size = 0"),
        ("lease_seconds = 60", 'lease_seconds = "60"'),
        ("connect_timeout_seconds = 3", "connect_timeout_seconds = 0"),
        ("statement_timeout_ms = 1000", "statement_timeout_ms = 1.5"),
        ("statement_timeout_ms = 1000", "statement_timeout_ms = true"),
    ],
)
def test_wrong_values_are_rejected(tmp_path: Path, old: str, new: str) -> None:
    write_config(tmp_path, VALID.replace(old, new))

    with pytest.raises(ConfigError):
        load_settings(tmp_path)


def test_missing_section_is_rejected(tmp_path: Path) -> None:
    write_config(
        tmp_path, "[normalize]\nbatch_size = 10\nlease_seconds = 60\nconnect_timeout_seconds = 3\n"
    )

    with pytest.raises(ConfigError):
        load_settings(tmp_path)
