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


def test_empty_zt_config_means_no_org_file():
    assert load_config(environ={"ZT_CONFIG": ""}) == load_config(environ={})


def test_org_config_overrides_only_given_keys():
    settings = load_config(environ={"ZT_CONFIG": str(FIXTURES / "org_override.toml")})
    assert settings.database.connect_timeout_seconds == 12
    assert settings.database.url_env == "DATABASE_URL"


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


def test_wheel_contains_and_uses_default_config(tmp_path):
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path / "dist")], cwd=ROOT, check=True
    )
    wheel = next((tmp_path / "dist").glob("*.whl"))
    installed = tmp_path / "installed"
    with ZipFile(wheel) as archive:
        assert "soc/default.toml" in archive.namelist()
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
