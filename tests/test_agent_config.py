"""에이전트 설정 로더: config/default.toml 위에 config/local.toml을 덮어쓴다(#209)."""

from pathlib import Path

from soc.agent.config import load_config

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"


def test_default_config_has_only_known_sections_and_no_secrets() -> None:
    config = load_config(REPO_CONFIG)
    assert {"llm", "agent", "tools"} <= set(config)
    assert config["llm"]["api_key_env"] == "LLM_API_KEY"
    for stage in ("l1", "l2", "l3"):
        assert isinstance(config["agent"][stage]["max_turns"], int)


def test_local_overrides_default(tmp_path: Path) -> None:
    (tmp_path / "default.toml").write_text(
        '[llm]\nbase_url = ""\nmodel = "a"\napi_key_env = "LLM_API_KEY"\n'
        "[agent.l1]\nmax_turns = 6\n[agent.l2]\nmax_turns = 12\n[tools]\n"
        "[other]\nignored = 1\n",
        encoding="utf-8",
    )
    (tmp_path / "local.toml").write_text(
        '[llm]\nmodel = "b"\n[agent.l1]\nmax_turns = 2\n', encoding="utf-8"
    )
    config = load_config(tmp_path)
    assert config["llm"] == {"base_url": "", "model": "b", "api_key_env": "LLM_API_KEY"}
    assert config["agent"]["l1"]["max_turns"] == 2
    assert config["agent"]["l2"]["max_turns"] == 12
    assert "other" not in config  # [llm]·[agent]·[tools]만 읽는다


def test_missing_local_is_fine(tmp_path: Path) -> None:
    (tmp_path / "default.toml").write_text('[llm]\nmodel = "a"\n', encoding="utf-8")
    assert load_config(tmp_path)["llm"]["model"] == "a"
