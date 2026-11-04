"""파이프와 에이전트가 주고받는 값: AgentTask, TaskPrompt, AgentResult, failure 값."""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from soc.contracts import CONTRACT_NAMES

Stage = Literal["l1", "l2", "l3"]
SubjectType = Literal["alert", "ticket", "incident", "hunt"]
Failure = Literal[
    "format_error",
    "evidence_id_error",
    "budget_exceeded",
    "rate_limited",
    "provider_error",
    "cancelled",
    "log_error",
]

STAGES: tuple[str, ...] = ("l1", "l2", "l3")
SUBJECT_TYPES: tuple[str, ...] = ("alert", "ticket", "incident", "hunt")
DOMAINS: tuple[str, ...] = ("web", "cloud")
FAILURES: tuple[str, ...] = (
    "format_error",
    "evidence_id_error",
    "budget_exceeded",
    "rate_limited",
    "provider_error",
    "cancelled",
    "log_error",
)

# 2~4층 프롬프트에 들어가면 안 되는 문구(#210). 부정문도 걸리므로 2·3층은 다른 말로 쓴다.
# 비교는 대소문자를 구분하지 않고 공백을 하나로 줄인 뒤 부분 문자열로 한다.
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "이전 지시",
    "지시를 무시",
    "ignore previous",
    "ignore all previous",
    "system prompt",
    "시스템 프롬프트",
    "대응을 실행",
)


def contains_forbidden(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text).casefold()
    return any(phrase.casefold() in normalized for phrase in FORBIDDEN_PHRASES)


# contracts/common/types.schema.json의 ID 모양과 같다. 끝의 \n을 받지 않도록 \Z를 쓴다.
_UUID7 = r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
EVIDENCE_ID = re.compile(rf"(alt|evt|agl)_{_UUID7}\Z")
_SUBJECT_ID = {
    "alert": re.compile(rf"alt_{_UUID7}\Z"),
    "ticket": re.compile(rf"tkt_{_UUID7}\Z"),
    "incident": re.compile(rf"inc_{_UUID7}\Z"),
    "hunt": re.compile(rf"(hnt|hrn)_{_UUID7}\Z"),
}


@dataclass(frozen=True)
class TaskPrompt:
    """4층 작업 프롬프트. 파이프가 쓴다. 금지 문구(FORBIDDEN_PHRASES)가 있으면 거부한다."""

    text: str
    version: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("TaskPrompt.text가 비어 있다")
        if contains_forbidden(self.text):
            raise ValueError("TaskPrompt.text에 금지 문구가 있다(FORBIDDEN_PHRASES)")
        if not isinstance(self.version, str) or not self.version:
            raise ValueError("TaskPrompt.version이 비어 있다")


@dataclass(frozen=True)
class AgentTask:
    """run_agent에 넘기는 작업 하나. 잘못된 값은 만들 때 ValueError로 거부한다.

    허용 도구 목록은 넣지 않는다. 도구는 stage로만 정한다.
    """

    stage: Stage
    task: str
    prompt: TaskPrompt
    data: Any
    output_contract: str
    cited_ids: Callable[[Any], Iterable[str]]
    subject_type: SubjectType
    subject_id: str
    allowed_evidence_ids: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    attempt: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_evidence_ids", tuple(self.allowed_evidence_ids))
        object.__setattr__(self, "domains", tuple(self.domains))
        if self.stage not in STAGES:
            raise ValueError(f"stage는 {', '.join(STAGES)} 중 하나다")
        if not isinstance(self.task, str) or not self.task:
            raise ValueError("task가 비어 있다")
        if not isinstance(self.prompt, TaskPrompt):
            raise ValueError("prompt는 TaskPrompt다")
        if self.output_contract not in CONTRACT_NAMES:
            raise ValueError("output_contract가 계약 이름이 아니다")
        if not callable(self.cited_ids):
            raise ValueError("cited_ids는 함수다")
        if self.subject_type not in SUBJECT_TYPES:
            raise ValueError(f"subject_type은 {', '.join(SUBJECT_TYPES)} 중 하나다")
        pattern = _SUBJECT_ID.get(self.subject_type)
        if not isinstance(self.subject_id, str) or not self.subject_id:
            raise ValueError("subject_id가 비어 있다")
        if pattern is not None and not pattern.match(self.subject_id):
            raise ValueError("subject_id가 subject_type의 ID 모양이 아니다")
        for evidence_id in self.allowed_evidence_ids:
            if not isinstance(evidence_id, str) or not EVIDENCE_ID.match(evidence_id):
                raise ValueError("allowed_evidence_ids에 근거 ID 모양이 아닌 값이 있다")
        for domain in self.domains:
            if domain not in DOMAINS:
                raise ValueError(f"domains는 {', '.join(DOMAINS)} 중에서 고른다")
        if type(self.attempt) is not int or self.attempt < 1:
            raise ValueError("attempt는 1 이상의 정수다")


@dataclass
class AgentResult:
    """run_agent의 결과. 실패해도 예외 대신 이 값을 돌려준다."""

    ok: bool
    output: Any
    failure: Failure | None
    detail: str | None
    run_id: str
    usage: dict[str, int] = field(default_factory=dict)
    cited_evidence_ids: list[str] = field(default_factory=list)
