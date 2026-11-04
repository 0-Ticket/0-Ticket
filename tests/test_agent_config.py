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


def test_default_llm_and_budget_values() -> None:
    config = load_config(REPO_CONFIG)
    llm = config["llm"]
    assert llm["base_url"] == "" and llm["model"] == ""  # 실제 값은 config/local.toml
    assert llm["strict_mode"] is True
    assert llm["timeout_seconds"] == 60
    assert llm["rate_limit_retries"] == 3
    assert "api_version" not in llm
    agent = config["agent"]
    assert [agent[s]["max_input_chars"] for s in ("l1", "l2", "l3")] == [32_000, 64_000, 48_000]
    assert [agent[s]["reasoning_effort"] for s in ("l1", "l2", "l3")] == ["low", "medium", "medium"]
    assert "max_tool_result_chars" not in agent["l1"]  # #211에서 넣는다


def test_default_config_has_provider_examples_only_as_comments() -> None:
    text = (REPO_CONFIG / "default.toml").read_text(encoding="utf-8")
    for example in (
        "openai.azure.com/openai/v1/",
        "https://api.groq.com/openai/v1",
        "http://localhost:11434/v1",
    ):
        lines = [line for line in text.splitlines() if example in line]
        assert lines, example
        assert all(line.lstrip().startswith("#") for line in lines), example


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
