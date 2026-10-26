"""Settings loader: config/default.toml overridden by the ZT_CONFIG file (D-015, K33)."""

import re
import subprocess
import sys
import tomllib
from pathlib import Path
from zipfile import ZipFile

import pytest

from soc.config import ConfigError, MissingSecretError, load_config, read_secret

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "config" / "default.toml"
FIXTURES = ROOT / "tests" / "fixtures" / "config"
ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def test_default_config_loads_without_org_file():
    settings = load_config(environ={})
    assert settings.database.url_env == "DATABASE_URL"
    assert settings.database.connect_timeout_seconds == 5
    assert settings.database.pool_max_size == 8
    assert settings.database.pool_timeout_seconds == 5
    assert settings.llm.provider == "openai_compatible"
    assert settings.llm.model == "granite4:micro"
    assert settings.llm.base_url == "http://localhost:11434/v1"
    assert settings.llm.api_key_env == "LLM_API_KEY"
    assert settings.llm.temperature == 0
    assert settings.vector_store.backend == "qdrant"
    assert settings.vector_store.url == "http://localhost:6333"
    assert settings.vector_store.collection == "closed_tickets"
    assert settings.l1.confidence_threshold == 0.8
    assert settings.l1.siem_window_minutes == 5
    assert settings.l1.similar_tickets == 5
    assert settings.l1.max_input_chars == 16000
    assert settings.l1.summary_top_rules == 5
    assert settings.l1.summary_records == 5
    assert settings.embedder.provider == "ollama"
    assert settings.embedder.base_url == "http://localhost:11434"
    assert settings.embedder.model == "bge-m3"
    assert settings.embedder.dimensions == 1024
    assert settings.vector_search.fusion_method == "rrf"


def test_default_normalize_and_lookup_settings():
    settings = load_config(environ={})
    assert settings.normalize.alias_dir == ""
    assert settings.normalize.batch_size == 500
    assert settings.normalize.max_parse_length == 16384
    assert settings.lookup.provider == "csv"


def test_default_branch_settings():
    settings = load_config(environ={})
    assert settings.branch.dedup_window_minutes == 10
    assert settings.branch.batch_size == 500
    # #87: duplicates are found in the representative table, so there is no scan limit.
    assert "dedup_scan_limit" not in type(settings.branch).model_fields
    assert settings.branch.rules_dir == ""


@pytest.mark.parametrize(
    "text",
    [
        "[branch]\ndedup_window_minutes = 0\n",
        "[branch]\nbatch_size = 0\n",
        # Removed in #87: an organization file that still sets it fails loudly.
        "[branch]\ndedup_scan_limit = 500\n",
    ],
)
def test_invalid_branch_settings_fail(tmp_path, text):
    org = tmp_path / "org.toml"
    org.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(org, environ={})


@pytest.mark.parametrize(
    "text",
    [
        "[l1]\nconfidence_threshold = 1.1\n",
        "[l1]\nconfidence_threshold = -0.1\n",
        "[l1]\nsiem_window_minutes = 0\n",
        "[l1]\nsimilar_tickets = 0\n",
        "[l1]\nmax_input_chars = 0\n",
        "[l1]\nsummary_top_rules = 0\n",
        "[l1]\nsummary_records = 0\n",
    ],
)
def test_invalid_l1_settings_fail(tmp_path, text):
    org = tmp_path / "org.toml"
    org.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(org, environ={})


@pytest.mark.parametrize(
    "text",
    [
        "[normalize]\nbatch_size = 0\n",
        "[normalize]\nmax_parse_length = 0\n",
        '[lookup]\nprovider = "No.Dots"\n',
    ],
)
def test_invalid_normalize_and_lookup_settings_fail(tmp_path, text):
    org = tmp_path / "org.toml"
    org.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(org, environ={})


def test_empty_zt_config_means_no_org_file():
    assert load_config(environ={"ZT_CONFIG": ""}) == load_config(environ={})


def test_org_config_overrides_only_given_keys():
    settings = load_config(environ={"ZT_CONFIG": str(FIXTURES / "org_override.toml")})
    assert settings.database.connect_timeout_seconds == 12
    assert settings.database.url_env == "DATABASE_URL"


def test_org_config_adds_agent_model_overrides():
    settings = load_config(FIXTURES / "llm_agent_override.toml", environ={})
    assert settings.llm.model == "org-default-model"
    assert settings.llm.agents["l1"].model == "l1-special-model"
    assert settings.llm.agents["new_agent"].model == "new-agent-model"


def test_default_llm_timeout_and_rate_limit_settings():
    settings = load_config(environ={}).llm
    assert settings.timeout_seconds == 300
    assert settings.rate_limit_retries == 3
    assert settings.rate_limit_wait_seconds == 5
    assert settings.rate_limit_max_wait_seconds == 60


def test_org_config_overrides_agent_timeout_without_model():
    settings = load_config(FIXTURES / "llm_agent_timeout_override.toml", environ={}).llm
    assert settings.timeout_seconds == 120
    assert settings.agents["web_specialist"].model is None
    assert settings.agents["web_specialist"].timeout_seconds == 240
    assert settings.agents["l1"].model == "l1-special-model"
    assert settings.agents["l1"].timeout_seconds is None


@pytest.mark.parametrize(
    "text",
    [
        "[llm]\ntimeout_seconds = 0\n",
        "[llm]\nrate_limit_retries = -1\n",
        "[llm]\nrate_limit_wait_seconds = -1\n",
        "[llm]\nrate_limit_max_wait_seconds = -1\n",
        "[llm.agents.l1]\ntimeout_seconds = 0\n",
    ],
)
def test_invalid_llm_timeout_settings_fail(tmp_path, text):
    org = tmp_path / "org.toml"
    org.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(org, environ={})


def test_default_config_denies_every_mcp_tool():
    settings = load_config(environ={})
    assert settings.mcp.max_query_limit == 500
    assert settings.mcp.allowed_tools == {}


def test_org_config_grants_mcp_tools_per_agent():
    settings = load_config(FIXTURES / "mcp_allowed_tools.toml", environ={})
    assert settings.mcp.allowed_tools == {"l1": ("query_siem",)}


def test_org_config_adds_an_agent_to_the_mcp_allowlist():
    settings = load_config(FIXTURES / "mcp_allowed_tools_added_agent.toml", environ={})
    assert settings.mcp.max_query_limit == 50
    assert sorted(settings.mcp.allowed_tools) == ["l1", "l3"]


def test_mcp_allowlist_rejects_a_repeated_tool(tmp_path):
    org = tmp_path / "org.toml"
    org.write_text('[mcp.allowed_tools]\nl1 = ["query_siem", "query_siem"]\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="mcp.allowed_tools.l1"):
        load_config(org, environ={})


def test_mcp_max_query_limit_below_one_fails(tmp_path):
    org = tmp_path / "org.toml"
    org.write_text("[mcp]\nmax_query_limit = 0\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mcp.max_query_limit"):
        load_config(org, environ={})


@pytest.mark.parametrize(
    "method", ["keyword_first", "rrf", "weighted_rrf", "dbsf", "weighted_score"]
)
def test_vector_fusion_method_can_be_selected_in_org_config(tmp_path, method):
    org = tmp_path / "org.toml"
    org.write_text(f'[vector_search]\nfusion_method = "{method}"\n', encoding="utf-8")

    assert load_config(org, environ={}).vector_search.fusion_method == method


def test_unknown_vector_fusion_method_fails(tmp_path):
    org = tmp_path / "org.toml"
    org.write_text('[vector_search]\nfusion_method = "something_else"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="vector_search.fusion_method"):
        load_config(org, environ={})


@pytest.mark.parametrize("section,key", [("vector_store", "url"), ("embedder", "base_url")])
def test_vector_service_urls_reject_credentials(tmp_path, section, key):
    org = tmp_path / "org.toml"
    org.write_text(f'[{section}]\n{key} = "http://test-user@localhost:6333"\n')

    with pytest.raises(ConfigError, match=f"{section}.{key}"):
        load_config(org, environ={})


def test_agent_model_override_rejects_unknown_fields(tmp_path):
    org = tmp_path / "org.toml"
    org.write_text("[llm.agents.l2]\nmodle = 'typo'\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"llm.agents.l2.modle"):
        load_config(org, environ={})


def test_explicit_path_beats_zt_config():
    settings = load_config(FIXTURES / "org_override.toml", environ={"ZT_CONFIG": "/nonexistent"})
    assert settings.database.connect_timeout_seconds == 12


def test_missing_org_config_file_fails(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(environ={"ZT_CONFIG": str(tmp_path / "missing.toml")})


def test_unknown_key_fails():
    with pytest.raises(ConfigError, match=r"database\.conect_timeout_seconds"):
        load_config(FIXTURES / "unknown_key.toml", environ={})


def test_table_replaced_by_value_fails(tmp_path):
    org = tmp_path / "org.toml"
    org.write_text('database = "postgresql"\n')
    with pytest.raises(ConfigError, match="database"):
        load_config(org, environ={})


def test_invalid_toml_fails(tmp_path):
    org = tmp_path / "org.toml"
    org.write_text("[database\n")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(org, environ={})


def test_invalid_value_fails_without_echoing_it(tmp_path):
    org = tmp_path / "org.toml"
    org.write_text("[database]\nconnect_timeout_seconds = -3\n")
    with pytest.raises(ConfigError) as caught:
        load_config(org, environ={})
    assert "database.connect_timeout_seconds" in str(caught.value)
    assert "-3" not in str(caught.value)


@pytest.mark.parametrize(
    "body",
    ["pool_max_size = 0", "pool_timeout_seconds = 0", "pool_max_size = -1"],
)
def test_bad_pool_settings_are_rejected(tmp_path, body):
    """#104: the screen API's pool size and wait must stay above zero."""
    org = tmp_path / "org.toml"
    org.write_text("[database]\n" + body + "\n")
    with pytest.raises(ConfigError) as caught:
        load_config(org, environ={})
    assert "database.pool_" in str(caught.value)


def test_secret_literal_in_env_name_field_fails_without_echoing_it():
    with pytest.raises(ConfigError) as caught:
        load_config(FIXTURES / "secret_literal.toml", environ={})
    message = str(caught.value)
    assert "database.url_env" in message
    assert "not-a-real-password" not in message
    assert caught.value.__cause__ is None


def test_secret_read_from_env_only():
    assert read_secret("ZT_TEST_SECRET", {"ZT_TEST_SECRET": "value-from-env"}) == "value-from-env"


def test_missing_secret_names_variable_only():
    with pytest.raises(MissingSecretError) as caught:
        read_secret("ZT_TEST_SECRET", {"OTHER": "unrelated-value"})
    assert "ZT_TEST_SECRET" in str(caught.value)
    assert "unrelated-value" not in str(caught.value)


def test_empty_secret_counts_as_missing():
    with pytest.raises(MissingSecretError):
        read_secret("ZT_TEST_SECRET", {"ZT_TEST_SECRET": ""})


def test_default_config_has_description_and_no_secrets():
    """Every value has a comment right above it, and secrets appear only as env names."""
    lines = DEFAULT.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("["):
            continue
        previous = lines[number - 1].strip() if number else ""
        assert previous.startswith("#"), f"line {number + 1} has no description: {stripped}"

    def walk(table, prefix=""):
        for key, value in table.items():
            if isinstance(value, dict):
                yield from walk(value, f"{prefix}{key}.")
            else:
                yield prefix + key, value

    for key, value in walk(tomllib.loads(DEFAULT.read_text(encoding="utf-8"))):
        if key.endswith("_env"):
            assert ENV_NAME.match(value), key


def test_default_env_names_are_listed_in_env_example():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    settings = load_config(environ={})
    assert f"# {settings.database.url_env}=" in example
    assert f"# {settings.llm.api_key_env}=" in example


def test_wheel_contains_and_uses_default_config(tmp_path):
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path / "dist")], cwd=ROOT, check=True
    )
    wheel = next((tmp_path / "dist").glob("*.whl"))
    installed = tmp_path / "installed"
    with ZipFile(wheel) as archive:
        assert "soc/default.toml" in archive.namelist()
        assert "soc/normalize/aliases/ait_suricata_alert.toml" in archive.namelist()
        assert "soc/normalize/aliases/ait_apache_access.toml" in archive.namelist()
        assert "soc/branch/rules/scenarios.toml" in archive.namelist()
        assert "soc/store/vectors/templates/decided_ticket.txt" in archive.namelist()
        assert "soc/store/vectors/templates/entity_sentence.txt" in archive.namelist()
        archive.extractall(installed)
    code = "\n".join(
        [
            "import sys",
            f"sys.path.insert(0, {str(installed)!r})",
            "import soc.config as config",
            f"assert config.__file__.startswith({str(installed)!r})",
            "print(config.load_config(environ={}).database.url_env)",
        ]
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, check=True, capture_output=True, text=True
    )
    assert result.stdout.strip() == "DATABASE_URL"
