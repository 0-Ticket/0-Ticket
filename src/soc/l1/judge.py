"""DB에서 L1 판정 대상을 읽고 결과를 적용하는 실행기 워커."""

import hashlib
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from soc.agent import AgentResult, AgentTask, run_agent
from soc.agent.types import TaskPrompt
from soc.contracts import to_datetime, to_epoch_ms, validate_contract
from soc.l1.ticketing import _insert_ticket, _make_ticket
from soc.similar.index import make_indexer
from soc.tools import services
from soc.tools.similar_cases import SERVICE as SERVICE_NAME

logger = logging.getLogger("soc.l1.judge")
Run = Callable[[AgentTask], AgentResult]
Indexer = Callable[[psycopg.Connection, str], None]
_DAY_MS = 86_400_000
_PROMPT = (
    "입력된 Alert 또는 Ticket의 Alert를 조사해 verdict를 작성한다. "
    "입력의 window_start_ms와 window_end_ms는 조회에 쓸 시간 범위다. "
    "근거는 실제 입력과 성공한 도구 결과에 있는 ID만 인용한다."
)


def _utcnow() -> datetime:
    """현재 UTC 시각을 반환한다."""
    return datetime.now(UTC)


def decide(subject_type: str, verdict: dict[str, Any], threshold: float) -> str:
    """대상 종류(alert/ticket), 검증된 Verdict, 확신도 임계값(0~1)으로 상태를 고른다."""
    decision = verdict["decision"]
    confident = verdict["confidence"] >= threshold
    if subject_type == "alert":
        return "promoted" if decision == "malicious" and confident else "held"
    if subject_type != "ticket":
        raise ValueError("subject_type은 alert 또는 ticket이어야 한다")
    if confident and decision == "benign":
        return "closed"
    if confident and decision == "malicious":
        return "escalated"
    return "held"


def _subject_type(subject_id: str) -> str:
    """Alert(alt_) 또는 Ticket(tkt_) ID의 접두사로 대상 종류를 고른다."""
    if subject_id.startswith("alt_"):
        return "alert"
    if subject_id.startswith("tkt_"):
        return "ticket"
    raise ValueError("L1 대상 ID가 아니다")


def _read_subject(
    conn: psycopg.Connection, subject_id: str, *, lock: bool = False
) -> dict[str, Any] | None:
    """DB 연결과 대상 ID로 대기 행을 읽는다. lock이면 행을 쓰기 잠금한다."""
    kind = _subject_type(subject_id)
    table = "alerts" if kind == "alert" else "tickets"
    suffix = " FOR UPDATE" if lock else ""
    row = conn.execute(f"SELECT * FROM {table} WHERE id = %s{suffix}", (subject_id,)).fetchone()
    if row is None:
        return None
    if kind == "alert" and (
        not isinstance(row["triage"], dict) or row["triage"].get("status") != "pending"
    ):
        return None
    if kind == "ticket" and row["status"] != "new":
        return None
    return dict(row)


def _alert_data(row: dict[str, Any]) -> dict[str, Any]:
    """DB Alert 행에서 모델에 필요한 값과 epoch 밀리초 시각을 추린다."""
    return {
        "id": row["id"],
        "time": to_epoch_ms(row["time"]),
        "severity": row["severity"],
        "title": row["title"],
        "rule_id": row["rule_id"],
        "entities": row["entities"],
        "assets": row["assets"],
    }


def _task(conn: psycopg.Connection, subject: dict[str, Any], attempt: int) -> AgentTask:
    """DB 연결, 판정 대상 행, 1부터 시작하는 시도 번호로 L1 작업을 만든다."""
    subject_id = subject["id"]
    kind = _subject_type(subject_id)
    if kind == "alert":
        alerts = [_alert_data(subject)]
        data: dict[str, Any] = {"alert": alerts[0]}
    else:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE id = ANY(%s)", (subject["alert_ids"],)
        ).fetchall()
        by_id = {row["id"]: row for row in rows}
        if len(by_id) != len(subject["alert_ids"]) or not by_id:
            raise LookupError("Ticket의 Alert를 찾지 못했다")
        alerts = [_alert_data(by_id[alert_id]) for alert_id in subject["alert_ids"]]
        data = {
            "ticket": {
                "id": subject_id,
                "origin": subject["origin"],
                "entities": subject["entities"],
            },
            "alerts": alerts,
        }
    times = [alert["time"] for alert in alerts]
    data.update(window_start_ms=min(times) - 6 * _DAY_MS, window_end_ms=max(times) + _DAY_MS)
    return AgentTask(
        stage="l1",
        task="l1_alert_triage" if kind == "alert" else "l1_ticket_judgment",
        prompt=TaskPrompt(text=_PROMPT, version=hashlib.sha256(_PROMPT.encode()).hexdigest()),
        data=data,
        output_contract="verdict",
        cited_ids=lambda output: output["evidence_ids"],
        subject_type=kind,
        subject_id=subject_id,
        allowed_evidence_ids=tuple(alert["id"] for alert in alerts),
        attempt=attempt,
    )


def _evidence_exists(conn: psycopg.Connection, evidence_ids: list[str]) -> bool:
    """DB 연결에서 Alert·Event·Agent Log 근거 ID 목록의 존재를 확인한다."""
    tables = {"alt_": "alerts", "evt_": "events", "agl_": "agent_logs"}
    for prefix, table in tables.items():
        ids = [item for item in evidence_ids if item.startswith(prefix)]
        if ids:
            row = conn.execute(
                f"SELECT count(*) AS count FROM {table} WHERE id = ANY(%s)", (ids,)
            ).fetchone()
            if row["count"] != len(ids):
                return False
    return True


class L1Worker:
    """L1 워커.

    stage는 실행기 단계, name은 단계 내 워커 이름이다.
    _database_url은 쓰기 DB 주소, _threshold는 확신도 임계값이다.
    _run은 AgentTask 실행 함수, _clock은 시간대가 있는 현재 시각을 반환하는 함수다.
    """

    stage = "l1"
    name = "l1_judge"

    def __init__(
        self,
        database_url: str,
        threshold: float = 0.8,
        *,
        run: Run = run_agent,
        clock: Callable[[], datetime] = _utcnow,
        indexer: Indexer | None = None,
    ) -> None:
        """database_url은 쓰기 DB 주소, threshold는 0~1 확신도 임계값이다.

        run은 AgentTask를 받아 AgentResult를 반환하고, clock은 현재 시각을 반환한다.
        indexer는 Ticket 판정을 저장한 직후 (연결, Ticket ID)로 부르는 유사 사례 색인 함수다(#313).
        """
        if type(threshold) not in (int, float) or not 0 <= threshold <= 1:
            raise ValueError("L1 confidence_threshold는 0과 1 사이다")
        self._database_url = database_url
        self._threshold = float(threshold)
        self._run = run
        self._clock = clock
        self._indexer = indexer

    def poll(self, limit: int) -> list[str]:
        """양의 정수 limit개 이하의 pending Alert와 new Ticket ID를 반환한다."""
        if type(limit) is not int or limit < 1:
            raise ValueError("limit은 양의 정수다")
        with psycopg.connect(self._database_url, autocommit=True) as conn:
            rows = conn.execute(
                "SELECT id FROM (SELECT id, time AS created FROM alerts "
                "WHERE triage->>'status' = 'pending' UNION ALL "
                "SELECT id, created_at AS created FROM tickets WHERE status = 'new') AS targets "
                "ORDER BY created, id LIMIT %s",
                (limit,),
            ).fetchall()
        return [row[0] for row in rows]

    def handle(self, subject_id: str) -> None:
        """Alert 또는 Ticket ID의 대기 상태를 확인하고 한 번 판정한다."""
        _subject_type(subject_id)
        try:
            with psycopg.connect(self._database_url, autocommit=True, row_factory=dict_row) as conn:
                subject = _read_subject(conn, subject_id)
                if subject is None:
                    return
                count = conn.execute(
                    "SELECT failures FROM l1_attempts WHERE subject_id = %s", (subject_id,)
                ).fetchone()
                task = _task(conn, subject, 1 if count is None else count["failures"] + 1)
                result = self._run(task)
                if result.failure == "cancelled":
                    return
                if not result.ok:
                    logger.warning("L1 실행 실패 subject=%s (%s)", subject_id, result.failure)
                    self._failure(conn, subject_id)
                    return
                self._apply(conn, subject_id, result.output)
                self._index(conn, subject_id)
        except Exception as exc:
            logger.warning("L1 처리 예외 subject=%s (%s)", subject_id, type(exc).__name__)
            with psycopg.connect(self._database_url, autocommit=True, row_factory=dict_row) as conn:
                self._failure(conn, subject_id)

    def _index(self, conn: psycopg.Connection, subject_id: str) -> None:
        """판정이 저장된 Ticket을 유사 사례 색인에 넣는다. 실패해도 L1 판정은 그대로 둔다(D-053)."""
        if self._indexer is None or _subject_type(subject_id) != "ticket":
            return
        try:
            self._indexer(conn, subject_id)
        except Exception as exc:
            logger.warning("유사 사례 색인 예외 subject=%s (%s)", subject_id, type(exc).__name__)

    def _failure(self, conn: psycopg.Connection, subject_id: str) -> None:
        """DB 연결에 대상 ID의 실패를 기록하고 세 번째면 보류한다."""
        kind = _subject_type(subject_id)
        with conn.transaction():
            if _read_subject(conn, subject_id, lock=True) is None:
                return
            row = conn.execute(
                "INSERT INTO l1_attempts (subject_id, subject_type, failures) VALUES (%s, %s, 1) "
                "ON CONFLICT (subject_id) DO UPDATE SET failures = l1_attempts.failures + 1 "
                "RETURNING failures",
                (subject_id, kind),
            ).fetchone()
            if row["failures"] >= 3:
                self._save(conn, subject_id, "held", None)

    def _apply(self, conn: psycopg.Connection, subject_id: str, verdict: dict[str, Any]) -> None:
        """DB 연결에서 대상 ID가 대기 중이면 검증할 Verdict를 적용한다."""
        validate_contract("verdict", verdict)
        with conn.transaction():
            subject = _read_subject(conn, subject_id, lock=True)
            if subject is None:
                return
            if not _evidence_exists(conn, verdict["evidence_ids"]):
                raise ValueError("근거를 찾지 못했다")
            state = decide(_subject_type(subject_id), verdict, self._threshold)
            self._save(conn, subject_id, state, verdict)
            if state == "promoted":
                ticket = _make_ticket(subject, "l1", to_epoch_ms(self._clock()))
                validate_contract("ticket", ticket)
                _insert_ticket(conn, ticket)

    def _save(
        self, conn: psycopg.Connection, subject_id: str, state: str, verdict: dict[str, Any] | None
    ) -> None:
        """DB 연결에 대상 ID의 새 상태와 Verdict 또는 null을 저장한다."""
        if _subject_type(subject_id) == "alert":
            conn.execute(
                "UPDATE alerts SET triage = %s WHERE id = %s",
                (Jsonb({"status": state, "verdict": verdict}), subject_id),
            )
        else:
            conn.execute(
                "UPDATE tickets SET status = %s, verdict = %s, updated_at = %s WHERE id = %s",
                (
                    state,
                    None if verdict is None else Jsonb(verdict),
                    to_datetime(to_epoch_ms(self._clock())),
                    subject_id,
                ),
            )


def build_worker(config: dict[str, Any]) -> L1Worker:
    """전체 TOML 설정의 L1 임계값과 DATABASE_URL 환경변수로 워커를 만든다."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL이 필요하다")
    threshold = config["agent"]["l1"]["confidence_threshold"]
    similar = services.snapshot().get(SERVICE_NAME)  # 실행기가 시작할 때 만든 임베더와 저장소(#313)
    indexer = None if similar is None else make_indexer(similar.embedder, similar.store)
    return L1Worker(database_url, threshold, indexer=indexer)
