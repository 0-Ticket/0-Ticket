"""analyzing Incident를 조사하고 검토 가능한 Artifact로 저장하는 L2 워커."""

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from soc.agent import AgentResult, AgentTask, run_agent
from soc.contracts import to_datetime, to_epoch_ms
from soc.l2.analyze.context import read_context
from soc.l2.analyze.store import save_failure, save_success
from soc.l2.analyze.tasks import make_investigate_task, make_report_task
from soc.l2.config import AnalyzeSettings, read_analyze_settings
from soc.l3.hunt.store import attack_names

Run = Callable[[AgentTask], AgentResult]
_RETRYABLE_REPORT_FAILURES = {"provider_error", "rate_limited", "log_error"}


def should_retry_report(failure: str | None) -> bool:
    return failure in _RETRYABLE_REPORT_FAILURES


class L2AnalyzeWorker:
    stage = "l2"
    name = "l2_analyze"

    def __init__(
        self,
        database_url: str,
        settings: AnalyzeSettings,
        *,
        max_range_days: int,
        asset_statement_timeout_ms: int,
        attack_version: str,
        run: Run = run_agent,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._database_url = database_url
        self._settings = settings
        self._max_range_days = max_range_days
        self._asset_statement_timeout_ms = asset_statement_timeout_ms
        self._attack_version = attack_version
        self._run = run
        self._clock = clock

    def poll(self, limit: int) -> list[str]:
        if type(limit) is not int or limit < 1:
            raise ValueError("limit은 양의 정수다")
        cutoff = to_epoch_ms(self._clock()) - self._settings.failure_retry_cooldown_ms
        with psycopg.connect(self._database_url, autocommit=True) as conn:
            rows = conn.execute(
                "SELECT id FROM incidents WHERE status = 'analyzing' OR "
                "(status = 'held' AND (details->'l2_analyze'->>'held_at')::bigint <= %s) "
                "ORDER BY updated_at, id LIMIT %s",
                (cutoff, limit),
            ).fetchall()
        return [row[0] for row in rows]

    def handle(self, incident_id: str) -> None:
        now_ms = to_epoch_ms(self._clock())
        with psycopg.connect(self._database_url, autocommit=True) as conn:
            with conn.transaction():
                row = conn.execute(
                    "SELECT status, analysis_round, details FROM incidents "
                    "WHERE id = %s FOR UPDATE",
                    (incident_id,),
                ).fetchone()
                if row is None or row[0] not in ("analyzing", "held"):
                    return
                if row[0] == "held":
                    details = row[2]
                    l2 = dict(details.get("l2_analyze", {}))
                    held_at = l2.get("held_at")
                    if type(held_at) is not int or (
                        now_ms - held_at < self._settings.failure_retry_cooldown_ms
                    ):
                        return
                    l2["failure_streak"] = 0
                    l2.pop("held_at", None)
                    conn.execute(
                        "UPDATE incidents SET status = 'analyzing', details = %s, updated_at = %s "
                        "WHERE id = %s",
                        (Jsonb({**details, "l2_analyze": l2}), to_datetime(now_ms), incident_id),
                    )
                read_round = row[1]
            context = read_context(
                conn,
                incident_id,
                self._settings,
                now_ms=now_ms,
                max_range_days=self._max_range_days,
                asset_statement_timeout_ms=self._asset_statement_timeout_ms,
            )
            if context is None:
                return
            attempt = read_round + 1
            investigation = self._run(
                make_investigate_task(
                    incident_id,
                    attempt=attempt,
                    data=context.investigate_data(),
                    allowed_evidence_ids=context.evidence_ids,
                )
            )
            if investigation.failure == "cancelled":
                return
            if not investigation.ok:
                self._save_failure(conn, incident_id, read_round, investigation, context)
                return

            report_task = make_report_task(
                incident_id,
                attempt=attempt,
                findings=investigation.output,
                incident=context.incident,
                assets=context.assets,
                previous_artifact=context.previous_artifact,
                asset_lookup_failed=context.asset_lookup_failed,
                context_evidence=context.evidence_ids,
            )
            report = self._run(report_task)
            if should_retry_report(report.failure):
                report = self._run(report_task)
            if report.failure == "cancelled":
                return
            if not report.ok:
                self._save_failure(conn, incident_id, read_round, report, context)
                return

            names = attack_names(conn, self._attack_version)
            save_success(
                conn,
                incident_id,
                expected_round=read_round,
                expected_ticket_ids=context.incident["ticket_ids"],
                findings=investigation.output,
                analysis=report.output,
                attack_names=names,
                asset_lookup_failed=context.asset_lookup_failed,
                now_ms=to_epoch_ms(self._clock()),
            )

    def _save_failure(
        self,
        conn: psycopg.Connection,
        incident_id: str,
        read_round: int,
        result: AgentResult,
        context: Any,
    ) -> None:
        save_failure(
            conn,
            incident_id,
            expected_round=read_round,
            failure=result.failure or "provider_error",
            run_id=result.run_id,
            asset_lookup_failed=context.asset_lookup_failed,
            max_failures=self._settings.max_failures,
            now_ms=to_epoch_ms(self._clock()),
        )


def build_worker(config: dict[str, Any]) -> L2AnalyzeWorker:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL이 필요하다")
    settings = read_analyze_settings(config["l2"])
    max_range_days = _positive(config["tools"]["max_range_days"], "tools.max_range_days")
    asset_timeout = _positive(
        config["asset_lookup"]["statement_timeout_ms"],
        "asset_lookup.statement_timeout_ms",
    )
    attack_version = config["l3"]["intel"]["attack"]["version"]
    if not isinstance(attack_version, str) or not attack_version:
        raise ValueError("l3.intel.attack.version이 필요하다")
    return L2AnalyzeWorker(
        database_url,
        settings,
        max_range_days=max_range_days,
        asset_statement_timeout_ms=asset_timeout,
        attack_version=attack_version,
    )


def _positive(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name}은 양의 정수다")
    return value
