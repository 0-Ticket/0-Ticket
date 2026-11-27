"""L3 Case 검색 도구가 쓰는 임베더와 `confirmed_cases` 저장소를 실행기가 시작할 때
한 번 만든다(#392, D-087).

임베더와 저장소는 #391의 색인 워커와 같은 인스턴스다(`index.get_embedder`·`get_store`).
그래서 상주 모델이 늘지 않는다(약 2.27GB, D-044). 색인 워커(l2 단계 스레드)와 이 도구(l3 단계의
도구 호출 스레드)가 같은 임베더를 동시에 쓴다. `embed`는 읽기만 하고 공유 상태를 바꾸지 않는다.
"""

import logging
from dataclasses import dataclass
from typing import Any

from soc.case_index.index import get_embedder, get_store
from soc.store import ConfigError, Embedder, StoreError, VectorStore
from soc.store.config import read_settings
from soc.tools import services
from soc.tools.confirmed_cases import NAME as TOOL_NAME
from soc.tools.confirmed_cases import SERVICE as SERVICE_NAME

logger = logging.getLogger("soc.case_index")

# 이 도구를 받는 태스크(D-086, soc.agent.types.TASK_NAMES). 단계 키 l3는 이 둘의 대체 키다
L3_TASKS = ("l3_hypothesize", "l3_verify")


@dataclass(frozen=True)
class ConfirmedCasesService:
    """도구가 쓰는 임베더와 `confirmed_cases` 저장소."""

    embedder: Embedder
    store: VectorStore


def build_service(config: dict[str, Any]) -> ConfirmedCasesService | None:
    """L3 태스크 중 하나에 도구가 허용돼 있을 때만 만든다. 모델은 처음 쓸 때 올라간다.

    허용 목록은 runner가 고르는 규칙과 같게 본다(D-086): 태스크 키가 있으면 그것을, 없으면 단계 키
    `l3`를 본다. Qdrant 주소 환경변수가 없거나 설정이 틀리면 None이고 종류만 로그에 남긴다.
    그러면 도구는 등록되지 않는다.
    """
    allowed = config.get("tools", {}).get("allowed", {})
    if not any(
        TOOL_NAME in allowed.get(task if task in allowed else "l3", []) for task in L3_TASKS
    ):
        return None
    try:
        settings = read_settings(config["store"])
        return ConfirmedCasesService(get_embedder(settings), get_store(settings))
    except (ConfigError, StoreError, KeyError, ValueError) as exc:
        logger.warning("Case 검색을 쓰지 않는다(%s)", type(exc).__name__)
        return None


def install_service(config: dict[str, Any]) -> ConfirmedCasesService | None:
    """build_service로 만들어 도구 공유 객체로 등록한다."""
    service = build_service(config)
    if service is not None:
        services.install(SERVICE_NAME, service)
    return service
