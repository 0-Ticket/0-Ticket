"""PostgreSQL Agent Log store (box 12, C8, D-002)."""

import json
from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg import errors

from soc.config import Settings
from soc.contracts import AgentStep, validate_contract
from soc.db import connect, connect_readonly
from soc.l1.agent_log import AgentLogEntry, ArtifactReference, DuplicateAgentStepError


def _step_dict(step: AgentStep | Mapping[str, Any]) -> dict[str, Any]:
    raw_step = step.model_dump(mode="json") if isinstance(step, AgentStep) else dict(step)
    return validate_contract("AgentStep", raw_step).model_dump(mode="json")


def _step_json(step: Mapping[str, Any]) -> str:
    return json.dumps(step, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _decode_entry(row: tuple[Any, ...]) -> AgentLogEntry:
    payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    step = validate_contract("AgentStep", payload)
    sha256, path = row[1], row[2]
    artifact = None if sha256 is None else ArtifactReference(sha256=sha256, path=path)
    return AgentLogEntry(step=step, artifact=artifact)


class PostgresAgentLogStore:
    """Persist immutable C8 rows and references to large-result artifact files."""

    def __init__(self, connection: psycopg.Connection, *, owns_connection: bool = False):
        self._connection = connection
        self._owns_connection = owns_connection

    def save_step(self, step: AgentStep, artifact: ArtifactReference | None = None) -> None:
        payload = _step_dict(step)
        key = (payload["subject_type"], payload["subject_id"], payload["step"])
        try:
            with self._connection.transaction():
                self._connection.execute(
                    """
                    INSERT INTO agent_steps
                        (subject_type, subject_id, step, created_at, payload)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (*key, payload["created_at"], _step_json(payload)),
                )
                if artifact is not None:
                    self._connection.execute(
                        """
                        INSERT INTO agent_step_artifacts
                            (subject_type, subject_id, step, sha256, artifact_path)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (*key, artifact.sha256, artifact.path),
                    )
        except errors.UniqueViolation:
            raise DuplicateAgentStepError("Agent Log step already exists") from None

    def list_steps(self, subject_type: str, subject_id: str) -> list[AgentLogEntry]:
        rows = self._connection.execute(
            """
            SELECT agent_steps.payload, artifacts.sha256, artifacts.artifact_path
            FROM agent_steps
            LEFT JOIN agent_step_artifacts AS artifacts
              USING (subject_type, subject_id, step)
            WHERE agent_steps.subject_type = %s AND agent_steps.subject_id = %s
            ORDER BY agent_steps.created_at, agent_steps.step
            """,
            (subject_type, subject_id),
        ).fetchall()
        return [_decode_entry(row) for row in rows]

    def close(self) -> None:
        if self._owns_connection:
            self._connection.close()


def create_postgresql_agent_log_store(
    settings: Settings, environ: Mapping[str, str] | None = None
) -> PostgresAgentLogStore:
    """Factory registered as ``postgresql.agent_log`` in the stores group."""
    return PostgresAgentLogStore(connect(settings, environ), owns_connection=True)


def create_postgresql_readonly_agent_log_store(
    settings: Settings, environ: Mapping[str, str] | None = None
) -> PostgresAgentLogStore:
    """The ``postgresql.readonly_agent_log`` factory: reads work, every write fails.

    For the screen API (box 27), which only reads the Agent Log
    (docs/security-policy.md 4).
    """
    return PostgresAgentLogStore(connect_readonly(settings, environ), owns_connection=True)
