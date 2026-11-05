"""화면용 API 응답 모델(#239). API 전용이고 contracts/의 계약이 아니다.

Hunt 부분은 생성 모델(soc.contracts.generated)을 그대로 쓴다. 감싸는 모양(목록, techniques, runs,
next_cursor)의 TypeScript 타입을 만드는 방법은 첫 화면 이슈가 정한다(데이터 계약, D-003).
밖에서 온 문자열과 LLM 출력(가설, 이유, details 안의 문자열, 뉴스 제목·요약·링크)은 가공하지 않고
JSON 문자열 그대로 돌려준다. 화면은 텍스트로만 보인다(D-019).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from soc.contracts.generated.hunt_schema import Hunt

HuntStatus = Literal["pending", "confirmed", "rejected", "inconclusive", "failed"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HuntListItem(_Model):
    id: str
    hunt_run_id: str
    status: HuntStatus
    hypothesis: str
    attack_techniques: list[str]
    confidence: float | None
    attempts: int
    verified_at: int | None
    created_at: int
    updated_at: int


class HuntPage(_Model):
    items: list[HuntListItem]
    next_cursor: str | None


class Technique(_Model):
    id: str
    # 설정 버전([l3.intel.attack] version)의 attack_techniques에 없으면 null
    name: str | None


class RunSummary(_Model):
    """Agent Log를 run_id로 묶은 요약. input·output 원문은 넣지 않는다."""

    run_id: str
    task: str | None
    attempt: int | None
    outcome: Literal["ok", "error"]
    failure: str | None
    tokens_in: int | None
    tokens_out: int | None
    started_at: int
    duration_ms: int


class HuntDetail(_Model):
    hunt: Hunt
    techniques: list[Technique]
    ticket_id: str | None
    runs: list[RunSummary]


class NewsItem(_Model):
    id: int
    source: str
    kind: Literal["rss", "cisa_kev"]
    title: str
    summary: str
    link: str | None
    published_at: int | None
    fetched_at: int
    updated_at: int


class NewsPage(_Model):
    items: list[NewsItem]
    next_cursor: str | None
