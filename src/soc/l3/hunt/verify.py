"""검증 run 워커: pending Hunt마다 가설을 우리 Alert·Event로 검증한다.

워커 모양은 #215 설계(stage, name, poll(limit), handle(subject_id))를 따른다. 실행기 등록은 후속
이슈에서 한다. handle은 멱등이다: pending이 아닌 Hunt는 건드리지 않고, 갱신은 읽은 상태가 그대로일
때만 한다.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from soc.agent import AgentResult, AgentTask, run_agent
from soc.contracts import to_epoch_ms, validate_contract
from soc.ids import new_id
from soc.l3.hunt import store
from soc.l3.hunt.prompts import load_prompt
from soc.l3.hunt.settings import HuntSettings

Run = Callable[[AgentTask], AgentResult]
RECORD_PREFIXES = ("alt_", "evt_")


def decide(output: dict[str, Any], *, threshold: float) -> tuple[str, list[str]]:
    """(저장할 결과, 낮춘 규칙). 근거가 모자란 confirmed·rejected는 inconclusive로 낮춘다."""
    result = output["result"]
    evidence = output["evidence_ids"]
    rules = []
    if result == "confirmed":
        if output["confidence"] < threshold:
            rules.append("threshold")
        if not any(i.startswith(RECORD_PREFIXES) for i in evidence):
            rules.append("no_record_evidence")
    elif result == "rejected" and not evidence:
        rules.append("no_evidence")
    return ("inconclusive" if rules else result), rules


def _key(entity: dict[str, Any]) -> tuple[Any, Any, Any]:
    return entity["type"], entity["value"], entity["role"]


def merge_entities(
    records: Sequence[dict[str, Any]], model: Sequence[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(합친 엔티티, 모델만 낸 엔티티). 레코드 엔티티가 앞이고, type·value·role이 같으면 하나다."""
    merged: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for entity in records:
        merged.setdefault(_key(entity), entity)
    from_records = set(merged)
    model_only: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for entity in model:
        if _key(entity) not in from_records:
            model_only.setdefault(_key(entity), entity)
            merged.setdefault(_key(entity), entity)
    return list(merged.values()), list(model_only.values())


def _cited(output: Any) -> list[str]:
    return output["evidence_ids"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class HuntVerifier:
    stage = "l3"
    name = "l3_hunt_verify"

    def __init__(
        self,
        database_url: str,
        settings: HuntSettings,
        *,
        run: Run = run_agent,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._database_url = database_url
        self._settings = settings
        self._run = run
        self._clock = clock

    def poll(self, limit: int | None) -> list[str]:
        """pending Hunt ID(오래된 것부터). None이면 전부."""
        with psycopg.connect(self._database_url, autocommit=True) as conn:
            return store.pending_hunt_ids(conn, limit)

    def handle(self, subject_id: str) -> None:
        with psycopg.connect(self._database_url, autocommit=True) as conn:
            hunt = store.read_hunt(conn, subject_id)
            if hunt is None or hunt["status"] != "pending":
                return
            names = store.attack_names(conn, self._settings.attack_version)
            now = self._clock()
            window_from = now - timedelta(days=self._settings.lookback_days)
            read_attempts = hunt["attempts"]
            # 모델 실행은 DB 트랜잭션 밖에서 한다
            result = self._run(
                AgentTask(
                    stage="l3",
                    task="l3_verify",
                    prompt=load_prompt("l3_verify"),
                    data={
                        "hypothesis": hunt["hypothesis"],
                        "attack_techniques": [
                            {"id": t, "name": names.get(t)} for t in hunt["attack_techniques"]
                        ],
                        "window": {"from": to_epoch_ms(window_from), "to": to_epoch_ms(now)},
                    },
                    output_contract="hunt_verification",
                    cited_ids=_cited,
                    subject_type="hunt",
                    subject_id=subject_id,
                    attempt=read_attempts + 1,
                )
            )
            now_ms = to_epoch_ms(self._clock())
            hunt = {**hunt, "attempts": read_attempts + 1, "updated_at": now_ms}
            if result.ok:
                hunt = self._verified(conn, hunt, result.output, now_ms)
            else:
                hunt = self._failed(hunt, result)
            validate_contract("hunt", hunt)
            ticket = _ticket(hunt, now_ms) if hunt["status"] == "confirmed" else None
            if ticket is not None:
                validate_contract("ticket", ticket)
            with conn.transaction():
                if not store.update_hunt(conn, hunt, read_attempts=read_attempts):
                    return  # 다른 실행이 먼저 처리했다
                if ticket is not None:
                    store.insert_ticket(conn, ticket)  # 이미 있으면 그 Ticket을 쓴다

    def _verified(
        self, conn: psycopg.Connection, hunt: dict[str, Any], output: dict[str, Any], now_ms: int
    ) -> dict[str, Any]:
        status, rules = decide(output, threshold=self._settings.confirm_threshold)
        records, missing = store.record_entities(conn, output["evidence_ids"])
        entities, model_only = merge_entities(records, output["entities"])
        details = {
            **hunt["details"],
            "model_only_entities": model_only,
            "missing_evidence_rows": missing,
        }
        if rules:
            details["downgraded"] = {"from": output["result"], "rules": rules}
        return {
            **hunt,
            "status": status,
            "confidence": output["confidence"],
            "reason": output["reason"],
            "evidence_ids": output["evidence_ids"],
            "entities": entities,
            "verified_at": now_ms,
            "details": details,
        }

    def _failed(self, hunt: dict[str, Any], result: AgentResult) -> dict[str, Any]:
        failures = [
            *hunt["details"].get("verify_failures", []),
            {"attempt": hunt["attempts"], "failure": result.failure, "run_id": result.run_id},
        ]
        exhausted = hunt["attempts"] >= self._settings.max_attempts
        return {
            **hunt,
            "status": "failed" if exhausted else "pending",
            "details": {**hunt["details"], "verify_failures": failures},
        }


def _ticket(hunt: dict[str, Any], now_ms: int) -> dict[str, Any]:
    """L3 Ticket. Alert 없이 Hunt를 가리키고, L2는 hunt_id로 Hunt의 근거를 따라간다."""
    return {
        "id": new_id("tkt"),
        "origin": "l3",
        "status": "escalated",
        "alert_ids": [],
        "hunt_id": hunt["id"],
        "entities": hunt["entities"],
        "verdict": None,
        "created_at": now_ms,
        "updated_at": now_ms,
        "details": {},
    }
