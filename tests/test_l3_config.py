"""L3 설정 로더: config/default.toml 위에 config/local.toml을 덮어쓰고 [l3]만 돌려준다(#221)."""

from pathlib import Path

import pytest

from soc.l3.config import load_config
from soc.l3.intel.collect import ConfigError, read_settings

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"


def test_default_config_reads_into_settings(default_config_dir: Path) -> None:
    config = load_config(default_config_dir)
    assert set(config) == {"l3"}
    settings = read_settings(config["l3"])
    assert [(s.name, s.kind) for s in settings.sources] == [
        ("boannews", "rss"),
        ("thehackernews", "rss"),
        ("cisa_kev", "cisa_kev"),
    ]
    assert all(s.url.startswith("https://") for s in settings.sources)
    assert settings.attack.version == "20.0"
    assert settings.attack.url.endswith("/enterprise-attack-20.0.json")
    assert settings.summary_max_chars == 1000
    # 공개 피드라 비밀 값도 환경변수 이름도 없다
    text = (REPO_CONFIG / "default.toml").read_text(encoding="utf-8")
    l3_part = text[text.index("[l3") :]
    assert "_env" not in l3_part


def test_local_overrides_default_and_only_l3_is_returned(tmp_path: Path) -> None:
    (tmp_path / "default.toml").write_text(
        '[llm]\nmodel = "a"\n'
        "[l3.intel]\nsummary_max_chars = 1000\n"
        '[l3.intel.attack]\nversion = "20.0"\nurl = "https://a.example.com/20.json"\n',
        encoding="utf-8",
    )
    (tmp_path / "local.toml").write_text(
        '[l3.intel.attack]\nversion = "19.2"\n[other]\nx = 1\n', encoding="utf-8"
    )
    config = load_config(tmp_path)
    assert config == {
        "l3": {
            "intel": {
                "summary_max_chars": 1000,
                "attack": {"version": "19.2", "url": "https://a.example.com/20.json"},
            }
        }
    }


def test_missing_local_is_fine(tmp_path: Path) -> None:
    (tmp_path / "default.toml").write_text("[l3.intel]\nsummary_max_chars = 5\n", encoding="utf-8")
    assert load_config(tmp_path) == {"l3": {"intel": {"summary_max_chars": 5}}}


def test_missing_l3_section_gives_empty(tmp_path: Path) -> None:
    (tmp_path / "default.toml").write_text('[llm]\nmodel = "a"\n', encoding="utf-8")
    assert load_config(tmp_path) == {"l3": {}}


def read_l3(directory: Path) -> dict:
    return load_config(directory)["l3"]


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c["intel"].pop("attack"),
        lambda c: c["intel"]["sources"][0].update(kind="atom"),
        lambda c: c["intel"]["sources"][0].update(url="http://feeds.example.com/x.xml"),
        lambda c: c["intel"]["sources"][1].update(name=c["intel"]["sources"][0]["name"]),
        lambda c: c["intel"]["sources"][0].update(name=""),
        lambda c: c["intel"].update(summary_max_chars=0),
        lambda c: c["intel"]["limits"]["rss"].update(max_bytes="5MB"),
        lambda c: c["intel"]["limits"].pop("cisa_kev"),
    ],
)
def test_bad_settings_are_rejected(change, default_config_dir: Path) -> None:
    l3 = read_l3(default_config_dir)
    change(l3)
    with pytest.raises(ConfigError):
        read_settings(l3)
