"""Settings: config/default.toml overridden by the organization file in ZT_CONFIG (D-015).

The organization file may only change keys the default file defines, so a typo
fails loudly instead of silently keeping the default. Secrets never live in a
settings file: a `*_env` key names an environment variable and `read_secret()`
reads its value. Error messages carry key paths and variable names, never values.
"""

import os
import tomllib
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

ORG_CONFIG_ENV = "ZT_CONFIG"

# Environment variable names only, so a URL or a key pasted here is rejected.
EnvName = Annotated[str, Field(pattern=r"^[A-Z_][A-Z0-9_]*$")]

# Tables keyed by agent name: the organization adds names here, so an unknown key
# is a new agent, not a typo. Every other table only takes the keys it defines.
OPEN_TABLES = frozenset({"llm.agents", "mcp.allowed_tools"})


class ConfigError(ValueError):
    """The settings files are missing, malformed, or hold an unknown or invalid key."""


class MissingSecretError(LookupError):
    """A secret's environment variable is not set."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DatabaseSettings(_Section):
    url_env: EnvName
    # The account agent tools read with (box 15, docs/security-policy.md 4).
    readonly_url_env: EnvName
    connect_timeout_seconds: int = Field(ge=1)


class AgentModelSettings(_Section):
    model: str = Field(min_length=1)


class LLMSettings(_Section):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    api_key_env: EnvName
    temperature: float = Field(ge=0, le=2)
    agents: dict[str, AgentModelSettings] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be an HTTP or HTTPS URL")
        if parsed.query or parsed.fragment:
            raise ValueError("must not include a query or fragment")
        return value.rstrip("/")


def _without_repeats(tools: tuple[str, ...]) -> tuple[str, ...]:
    if len(set(tools)) != len(tools):
        raise ValueError("lists the same tool twice")
    return tools


ToolName = Annotated[str, Field(min_length=1)]
# The allowlist is read on every call, so a repeated name is a mistake worth failing on.
AgentTools = Annotated[tuple[ToolName, ...], AfterValidator(_without_repeats)]


class SpecialistSettings(_Section):
    """Box 14: how much of a source's flow a specialist reads around the alerts."""

    flow_window_minutes: int = Field(ge=1)
    flow_limit: int = Field(ge=1)


class McpSettings(_Section):
    max_query_limit: int = Field(ge=1)
    allowed_tools: dict[str, AgentTools] = Field(default_factory=dict)


class DirectFileSettings(_Section):
    """One dataset file the direct adapter replays, and how its lines become C2."""

    path: str = Field(min_length=1)
    kind: Literal["alert", "event"]
    scenario: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    format: Literal["text", "jsonl"]


class DirectSiemSettings(_Section):
    files: tuple[DirectFileSettings, ...]

    @model_validator(mode="after")
    def _unique_file_names(self) -> "DirectSiemSettings":
        # raw_id is raw_<file name>_<line>, so two files with one name would clash.
        names = [Path(entry.path).name for entry in self.files]
        if len(names) != len(set(names)):
            raise ValueError("each file name must be unique")
        return self


class SiemSettings(_Section):
    adapter: str
    base_url: str
    token_env: EnvName
    verify_tls: bool
    timeout_seconds: int = Field(ge=1)
    batch_size: int = Field(ge=1)
    direct: DirectSiemSettings


class StoreSettings(_Section):
    # Stores are registered as "<backend>.<kind>", so a dot in the name would be ambiguous.
    backend: str = Field(pattern=r"^[a-z0-9_]+$")
    raw_retention_days: int = Field(ge=0)


class AgentLogSettings(_Section):
    artifact_dir: str = Field(min_length=1)


class EvidenceQueueSettings(_Section):
    # The name registered in the evidence_queues group; same naming rule as store.backend.
    backend: str = Field(pattern=r"^[a-z0-9_]+$")
    # Retries after the first attempt (D-034, shared by L1 and L2).
    max_retries: int = Field(ge=0)


class NormalizeSettings(_Section):
    # Organization alias table folder (box 4, C20). Empty: default tables only.
    alias_dir: str
    batch_size: int = Field(ge=1)
    # Longest text a parse pattern is applied to. Longer values fail as bad_value.
    max_parse_length: int = Field(ge=1)


class LookupSettings(_Section):
    # The name registered in the lookups group; same naming rule as store.backend.
    provider: str = Field(pattern=r"^[a-z0-9_]+$")


def _validate_http_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("must be an HTTP or HTTPS URL")
    if parsed.query or parsed.fragment:
        raise ValueError("must not include a query or fragment")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("must not include credentials")
    return value.rstrip("/")


class VectorStoreSettings(_Section):
    backend: str = Field(pattern=r"^[a-z0-9_]+$")
    url: str = Field(min_length=1)
    collection: str = Field(min_length=1)
    timeout_seconds: int = Field(ge=1)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_http_base_url(value)


class EmbedderSettings(_Section):
    provider: str = Field(pattern=r"^[a-z0-9_]+$")
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    dimensions: int = Field(ge=1)
    timeout_seconds: int = Field(ge=1)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return _validate_http_base_url(value)


FusionMethod = Literal[
    "keyword_first",
    "rrf",
    "weighted_rrf",
    "dbsf",
    "weighted_score",
]


class VectorSearchSettings(_Section):
    fusion_method: FusionMethod
    keyword_weight: float = Field(gt=0, allow_inf_nan=False)
    vector_weight: float = Field(gt=0, allow_inf_nan=False)
    rrf_rank_constant: int = Field(ge=1)


class ApiSettings(_Section):
    """Where the screen API listens (box 27). It serves read-only L1 results."""

    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)


class Settings(_Section):
    """Typed settings. Each box issue adds its own section here and in default.toml."""

    api: ApiSettings
    database: DatabaseSettings
    evidence_queue: EvidenceQueueSettings
    embedder: EmbedderSettings
    llm: LLMSettings
    lookup: LookupSettings
    mcp: McpSettings
    normalize: NormalizeSettings
    siem: SiemSettings
    specialist: SpecialistSettings
    store: StoreSettings
    agent_log: AgentLogSettings
    vector_search: VectorSearchSettings
    vector_store: VectorStoreSettings


def _default_config_text() -> str:
    packaged = files(__package__).joinpath("default.toml")
    if packaged.is_file():
        return packaged.read_text(encoding="utf-8")
    # Editable installs expose src/ directly. Resolve from this module, never cwd.
    module_dir = Path(__file__).resolve().parent
    root = module_dir.parents[1]
    default = root / "config" / "default.toml"
    if module_dir == root / "src" / "soc" and default.is_file():
        return default.read_text(encoding="utf-8")
    raise ConfigError("Packaged default settings are missing")


def _parse(text: str, label: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        # The decoder reports a position only; it does not repeat file content.
        raise ConfigError(f"{label} is not valid TOML: {error}") from None


def _merge(base: dict[str, Any], override: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        path = prefix + key
        if key not in base:
            raise ConfigError(f"Unknown setting '{path}': not defined in config/default.toml")
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise ConfigError(f"Setting '{path}' must be a table")
            if path in OPEN_TABLES:
                # Agent names are extension points. Pydantic validates each entry
                # while the containing table accepts newly added agents.
                merged[key] = {**base[key], **value}
            else:
                merged[key] = _merge(base[key], value, path + ".")
        elif isinstance(value, dict):
            raise ConfigError(f"Setting '{path}' must be a value, not a table")
        else:
            merged[key] = value
    return merged


def load_config(
    path: str | Path | None = None, environ: Mapping[str, str] | None = None
) -> Settings:
    """Load the default settings and apply the organization file over them.

    The organization file is `path` if given, else the file named by ZT_CONFIG.
    An empty ZT_CONFIG means no organization file.
    """
    environ = os.environ if environ is None else environ
    data = _parse(_default_config_text(), "config/default.toml")
    org_path = path if path is not None else environ.get(ORG_CONFIG_ENV) or None
    if org_path is not None:
        org_file = Path(org_path)
        if not org_file.is_file():
            raise ConfigError(f"Organization settings file not found: {org_file}")
        data = _merge(data, _parse(org_file.read_text(encoding="utf-8"), str(org_file)))
    try:
        return Settings.model_validate(data)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors(include_input=False, include_url=False)
        )
        # Drop the pydantic error: its message would repeat the rejected value.
        raise ConfigError(f"Invalid settings: {problems}") from None


def read_secret(env_name: str, environ: Mapping[str, str] | None = None) -> str:
    """Read a secret from the environment variable a `*_env` setting names."""
    environ = os.environ if environ is None else environ
    value = environ.get(env_name)
    if not value:
        raise MissingSecretError(f"Environment variable {env_name} is not set (see .env.example)")
    return value
