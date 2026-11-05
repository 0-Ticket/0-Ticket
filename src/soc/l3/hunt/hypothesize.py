"""가설 생성 run: 최근 뉴스·Case로 가설을 세우고 pending Hunt로 저장한다."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import psycopg

from soc.agent import AgentResult, AgentTask
from soc.contracts import to_epoch_ms, validate_contract
from soc.ids import new_id
from soc.l3.hunt import store
from soc.l3.hunt.prompts import load_prompt
from soc.l3.hunt.settings import HuntSettings

Run = Callable[[AgentTask], AgentResult]


@dataclass
class HypothesizeResult:
    """건수만 담는다. 가설 문장 같은 본문은 담지 않는다."""

    hunt_run_id: str | None = None
    saved: list[str] = field(default_factory=list)
    unknown_technique: int = 0  # 설정 버전의 attack_techniques에 없는 기법을 낸 가설
    over_limit: int = 0  # max_hypotheses를 넘어 버린 가설
    dropped_refs: int = 0  # 입력에 없던 뉴스·Case 참조
    failure: str | None = None  # 가설 생성 run의 failure
    skipped: str | None = None  # run을 하지 않은 이유


def _no_evidence(output: Any) -> tuple[str, ...]:
    """뉴스·Case 참조는 근거 ID(alt_·evt_·agl_)가 아니다. 입력과의 대조는 코드가 한다."""
    return ()


def hypothesize(
    conn: psycopg.Connection, settings: HuntSettings, *, run: Run, now: datetime
) -> HypothesizeResult:
    """conn은 autocommit 연결이다. 한 run의 Hunt는 한 트랜잭션으로 쓴다."""
    techniques = store.attack_names(conn, settings.attack_version)
    if not techniques:
        # 기법을 확인할 수 없으면 모든 가설이 버려지므로 LLM을 부르지 않는다
        return HypothesizeResult(skipped="no_attack_version")

    news = store.recent_news(
        conn, since=now - timedelta(days=settings.news_window_days), limit=settings.news_limit
    )
    cases = store.recent_cases(conn, limit=settings.case_limit)
    hunt_run_id = new_id("hrn")
    result = HypothesizeResult(hunt_run_id=hunt_run_id)

    agent_result = run(
        AgentTask(
            stage="l3",
            task="l3_hypothesize",
            prompt=load_prompt("l3_hypothesize"),
            data={"news": news, "cases": cases, "max_hypotheses": settings.max_hypotheses},
            output_contract="hunt_hypotheses",
            cited_ids=_no_evidence,
            subject_type="hunt",
            subject_id=hunt_run_id,
            allowed_evidence_ids=(),
        )
    )
    if not agent_result.ok:
        result.failure = agent_result.failure
        return result

    hypotheses = agent_result.output["hypotheses"]
    result.over_limit = max(0, len(hypotheses) - settings.max_hypotheses)
    news_by_id = {n["id"]: n for n in news}
    case_ids = {c["id"] for c in cases}
    created = to_epoch_ms(now)
    hunts = []
    for hypothesis in hypotheses[: settings.max_hypotheses]:
        if any(t not in techniques for t in hypothesis["attack_techniques"]):
            result.unknown_technique += 1
            continue
        cited_news = [news_by_id[i] for i in hypothesis["news_ids"] if i in news_by_id]
        cited_cases = [i for i in hypothesis["case_ids"] if i in case_ids]
        result.dropped_refs += len(hypothesis["news_ids"]) - len(cited_news)
        result.dropped_refs += len(hypothesis["case_ids"]) - len(cited_cases)
        hunt = {
            "id": new_id("hnt"),
            "hunt_run_id": hunt_run_id,
            "status": "pending",
            "hypothesis": hypothesis["hypothesis"],
            "attack_techniques": hypothesis["attack_techniques"],
            "confidence": None,
            "reason": None,
            "evidence_ids": [],
            "entities": [],
            "attempts": 0,
            "verified_at": None,
            "created_at": created,
            "updated_at": created,
            # 뉴스는 다시 받으면 내용이 바뀌므로(#221) 그 시점의 제목·요약을 복사한다
            "details": {"sources": {"news": cited_news, "case_ids": cited_cases}},
        }
        validate_contract("hunt", hunt)
        hunts.append(hunt)
    if hunts:
        with conn.transaction():
            store.insert_hunts(conn, hunts)
    result.saved = [h["id"] for h in hunts]
    return result
