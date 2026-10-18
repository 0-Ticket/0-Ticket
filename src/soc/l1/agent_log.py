"""Agent Log lifecycle and storage boundary (box 12, C8)."""

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from soc.config import Settings
from soc.contracts import AgentStep, validate_contract
from soc.l1.tickets import TicketNotFoundError, TicketStore, open_ticket_store
from soc.plugins import PluginRegistry

SUBJECT_TYPES = frozenset({"alert", "ticket", "incident", "hunt"})
EXCERPT_LIMIT = 2000
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:password|passwd|token|api[_-]?key|secret|authorization|"
    r"access[_-]?key|client[_-]?secret)\b[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\r\n,;}]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+")
_UNSET = object()


class AgentLogStore(Protocol):
    """Storage operations required by the C8 Agent Log service."""

    def save_step(
        self, step: AgentStep, artifact: "ArtifactReference | None" = None
    ) -> None: ...

    def list_steps(self, subject_type: str, subject_id: str) -> list["AgentLogEntry"]: ...

    def close(self) -> None: ...


class AgentLogSerializationError(ValueError):
    """A large tool result could not be safely serialized for the artifact store."""


class DuplicateAgentStepError(ValueError):
    """A C8 step already exists for this subject and step number."""


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    """Hash and relative path for the portion of a large result after its excerpt."""

    sha256: str
    path: str


@dataclass(frozen=True, slots=True)
class AgentLogEntry:
    """A validated C8 row and optional reference to its remaining large output."""

    step: AgentStep
    artifact: ArtifactReference | None = None


def open_agent_log_store(
    settings: Settings,
    environ: Mapping[str, str] | None = None,
    registry: PluginRegistry | None = None,
) -> AgentLogStore:
    """Open the selected Agent Log backend through the shared store registry."""
    from soc.store import open_store

    kwargs = {}
    if environ is not None:
        kwargs["environ"] = environ
    if registry is not None:
        kwargs["registry"] = registry
    return open_store("agent_log", settings, **kwargs)


class AgentLogService:
    """Validate, redact, persist, and query C8 AgentStep records."""

    def __init__(
        self,
        store: AgentLogStore,
        artifact_dir: str | Path,
        *,
        secrets: tuple[str, ...] = (),
        ticket_store_factory: Callable[[], TicketStore] | None = None,
    ):
        self._store = store
        self._artifact_dir = Path(artifact_dir)
        self._secrets = tuple(secret for secret in secrets if secret)
        self._ticket_store_factory = ticket_store_factory

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        environ: Mapping[str, str] | None = None,
        registry: PluginRegistry | None = None,
    ) -> "AgentLogService":
        env = os.environ if environ is None else environ
        secret_names = (
            settings.database.url_env,
            settings.llm.api_key_env,
            settings.siem.token_env,
        )
        secrets = tuple(env[name] for name in secret_names if env.get(name))

        def ticket_store_factory() -> TicketStore:
            return open_ticket_store(settings, environ=env, registry=registry)

        return cls(
            open_agent_log_store(settings, environ=env, registry=registry),
            settings.agent_log.artifact_dir,
            secrets=secrets,
            ticket_store_factory=ticket_store_factory,
        )

    def __call__(self, step: AgentStep) -> None:
        """Allow the service itself to be passed as call_llm(record_step=...)."""
        self.record(step)

    def record(self, step: AgentStep | Mapping[str, Any], *, full_result: object = _UNSET) -> None:
        """Persist one C8 step and optionally the remainder of a large result."""
        raw_step = step.model_dump(mode="json") if isinstance(step, AgentStep) else dict(step)
        validated = validate_contract("AgentStep", raw_step).model_dump(mode="json")
        text_fields = (
            "agent",
            "tool",
            "prompt_version",
            "input_excerpt",
            "output_excerpt",
            "model",
        )
        for field in text_fields:
            if validated[field] is not None:
                value = self._redact(validated[field])
                validated[field] = value[:EXCERPT_LIMIT] if field.endswith("excerpt") else value

        artifact = None
        if full_result is not _UNSET:
            result_text = self._redact(_serialize_result(full_result))
            validated["output_excerpt"] = result_text[:EXCERPT_LIMIT]
            remainder = result_text[EXCERPT_LIMIT:]
            if remainder:
                artifact = self._write_artifact(remainder)

        safe_step = validate_contract("AgentStep", validated)
        self._store.save_step(safe_step, artifact)

    def list_for_subject(self, subject_type: str, subject_id: str) -> list[AgentLogEntry]:
        """Return one subject's C8 records in chronological order."""
        _validate_subject(subject_type, subject_id)
        return self._ordered(self._store.list_steps(subject_type, subject_id))

    def list_for_ticket(self, ticket_id: str) -> list[AgentLogEntry]:
        """Return Ticket steps and its linked Alert steps, ordered by C8 created_at."""
        if self._ticket_store_factory is None:
            raise RuntimeError("Ticket lookup is not configured for this Agent Log service")
        ticket_store = self._ticket_store_factory()
        try:
            raw_ticket = ticket_store.get(ticket_id)
        finally:
            close = getattr(ticket_store, "close", None)
            if callable(close):
                close()
        if raw_ticket is None:
            raise TicketNotFoundError("Ticket not found")

        ticket = validate_contract("Ticket", raw_ticket)
        subjects = [("alert", alert_id) for alert_id in dict.fromkeys(ticket.alert_ids)]
        subjects.append(("ticket", ticket.ticket_id))
        entries = [
            entry
            for subject_type, subject_id in subjects
            for entry in self._store.list_steps(subject_type, subject_id)
        ]
        return self._ordered(entries)

    def close(self) -> None:
        self._store.close()

    def _redact(self, value: str) -> str:
        redacted = value
        for secret in sorted(set(self._secrets), key=len, reverse=True):
            redacted = redacted.replace(secret, "[REDACTED]")
        redacted = _SECRET_ASSIGNMENT.sub(r'\1"[REDACTED]"', redacted)
        return _BEARER_TOKEN.sub(r"\1[REDACTED]", redacted)

    def _write_artifact(self, remainder: str) -> ArtifactReference:
        content = remainder.encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        relative_path = Path("sha256") / f"{digest}.txt"
        destination = self._artifact_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=destination.parent,
                prefix=".agent-log-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(remainder)
                temp_path = Path(temporary.name)
            temp_path.replace(destination)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        return ArtifactReference(sha256=digest, path=relative_path.as_posix())

    @staticmethod
    def _ordered(entries: list[AgentLogEntry]) -> list[AgentLogEntry]:
        return sorted(
            entries,
            key=lambda entry: (
                entry.step.created_at,
                entry.step.subject_type,
                entry.step.subject_id,
                entry.step.step,
            ),
        )


def _validate_subject(subject_type: str, subject_id: str) -> None:
    if subject_type not in SUBJECT_TYPES:
        raise ValueError("Unknown Agent Log subject type")
    if not isinstance(subject_id, str) or not subject_id:
        raise ValueError("Agent Log subject ID must be a non-empty string")


def _serialize_result(value: object) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            raise AgentLogSerializationError("Tool result must be UTF-8 text") from None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        raise AgentLogSerializationError("Tool result must be JSON serializable") from None
