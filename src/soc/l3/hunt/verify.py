"""검증 run 워커: pending Hunt마다 가설을 우리 Alert·Event로 검증한다.

워커 모양은 #215 설계(stage, name, poll(limit), handle(subject_id))를 따른다. 실행기에는
[executor.l3] workers의 "soc.l3.hunt.verify:build_worker"로 등록한다(#245). handle은 멱등이다:
pending이 아닌 Hunt는 건드리지 않고, 갱신은 읽은 상태가 그대로일 때만 한다. 종료로 끊긴 run
(failure = "cancelled")은 시도로 세지 않는다.
"""

import logging
import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import psycopg

from soc.agent import AgentResult, AgentTask, run_agent
from soc.contracts import to_epoch_ms, validate_contract
from soc.evidence import issue
from soc.ids import new_id
from soc.l3.hunt import store
from soc.l3.hunt.prompts import load_prompt
from soc.l3.hunt.settings import ConfigError, HuntSettings, lookback_window, read_hunt_settings
from soc.ticketing import clean_title

logger = logging.getLogger(__name__)

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
        siem_config: dict[str, Any] | None = None,
        evidence_profile: str = "",
    ) -> None:
        self._database_url = database_url
        self._settings = settings
        # 근거 발급(#382). 인용된 문서가 없으면 쓰이지 않는다
        self._siem_config = siem_config or {}
        self._evidence_profile = evidence_profile
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
                        "window": lookback_window(self._settings, now),
                    },
                    output_contract="hunt_verification",
                    cited_ids=_cited,
                    cited_refs=lambda output: output["siem_refs"],
                    subject_type="hunt",
                    subject_id=subject_id,
                    attempt=read_attempts + 1,
                )
            )
            if result.failure == "cancelled":
                # 종료로 끊긴 run은 시도로 세지 않는다. Hunt는 그대로 pending이고 다음 실행에서 다시
                # 한다. 그 run은 Agent Log에만 남는다(#215 약속, #245)
                return
            now_ms = to_epoch_ms(self._clock())
            hunt = {**hunt, "attempts": read_attempts + 1, "updated_at": now_ms}
            if result.ok:
                # 인용한 SIEM 문서를 먼저 발급한다(#382). 그 evt_ ID의 엔티티를 아래
                # record_entities가 읽는다. 발급 실패는 그 근거만 버리고 계속한다
                output = self._issue(conn, result, now_ms)
                hunt = self._verified(conn, hunt, output, now_ms)
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

    def _issue(self, conn: psycopg.Connection, result: AgentResult, now_ms: int) -> dict[str, Any]:
        """발급한 evt_ ID를 evidence_ids에 더하고 siem_refs를 뗀 출력(#382).

        발급 전 문서는 ID가 없어 Hunt에 남기면 되돌릴 수 없는 포인터가 된다.
        """
        output = {k: v for k, v in result.output.items() if k != "siem_refs"}
        if not result.cited_siem_refs:
            return output
        issued = issue(
            conn,
            result.cited_siem_refs,
            siem_config=self._siem_config,
            siem_profile=self._evidence_profile,
            now_ms=now_ms,
        )
        if issued.dropped:
            logger.warning("L3 근거 발급 실패 %d건", issued.dropped)
        existing = output["evidence_ids"]
        added = [i for i in issued.evidence_ids.values() if i not in existing]
        output["evidence_ids"] = [*existing, *added]
        return output

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


def database_url_from_env() -> str:
    """실행기 워커가 쓰는 DATABASE_URL. 없으면 ConfigError(주소는 메시지에 넣지 않는다)."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ConfigError("환경변수 DATABASE_URL이 없다")
    return url


def build_worker(config: dict[str, Any]) -> HuntVerifier:
    """실행기 등록 함수(#215). config는 설정 전체이고 [l3]와 [tools.siem]을 읽는다."""
    siem = config.get("tools", {}).get("siem", {})
    evidence_profile = siem.get("evidence_siem_profile", "")
    if not isinstance(evidence_profile, str) or not evidence_profile:
        raise ConfigError("[tools.siem] evidence_siem_profile이 필요하다")
    return HuntVerifier(
        database_url_from_env(),
        read_hunt_settings(config.get("l3", {})),
        siem_config=dict(siem),
        evidence_profile=evidence_profile,
    )


def _ticket(hunt: dict[str, Any], now_ms: int) -> dict[str, Any]:
    """L3 Ticket. Alert 없이 Hunt를 가리키고, L2는 hunt_id로 Hunt의 근거를 따라간다."""
    return {
        "id": new_id("tkt"),
        "title": clean_title(hunt["hypothesis"]),  # LLM 출력이라 데이터·텍스트로만 쓴다
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
