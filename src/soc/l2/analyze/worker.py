"""analyzing Incident를 조사하고 검토 가능한 Artifact로 저장하는 L2 워커."""

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import psycopg

from soc.agent import AgentResult, AgentTask, run_agent
from soc.contracts import to_epoch_ms
from soc.l2.analyze.context import read_context
from soc.l2.analyze.store import mark_stopped, save_failure, save_success
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
        with psycopg.connect(self._database_url, autocommit=True) as conn:
            rows = conn.execute(
                "SELECT id FROM incidents WHERE status = 'analyzing' AND "
                "(analysis_round < %s OR (analysis_round >= %s AND NOT "
                "(COALESCE(details->'l2_analyze', '{}'::jsonb) ? 'stopped'))) "
                "ORDER BY updated_at, id LIMIT %s",
                (
                    self._settings.max_analysis_rounds,
                    self._settings.max_analysis_rounds,
                    limit,
                ),
            ).fetchall()
        return [row[0] for row in rows]

    def handle(self, incident_id: str) -> None:
        now_ms = to_epoch_ms(self._clock())
        with psycopg.connect(self._database_url, autocommit=True) as conn:
            row = conn.execute(
                "SELECT status, analysis_round FROM incidents WHERE id = %s", (incident_id,)
            ).fetchone()
            if row is None or row[0] != "analyzing":
                return
            read_round = row[1]
            if read_round >= self._settings.max_analysis_rounds:
                mark_stopped(conn, incident_id, expected_round=read_round, now_ms=now_ms)
                return
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
                self._save_failure(conn, incident_id, read_round, investigation, context, now_ms)
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
                self._save_failure(conn, incident_id, read_round, report, context, now_ms)
                return

            names = attack_names(conn, self._attack_version)
            save_success(
                conn,
                incident_id,
                expected_round=read_round,
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
        now_ms: int,
    ) -> None:
        save_failure(
            conn,
            incident_id,
            expected_round=read_round,
            failure=result.failure or "provider_error",
            run_id=result.run_id,
            asset_lookup_failed=context.asset_lookup_failed,
            now_ms=now_ms,
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
