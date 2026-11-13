"""실행기가 시작할 때 임베더와 유사 사례 저장소를 한 번 만든다(#313, D-053)."""

import logging
from dataclasses import dataclass
from typing import Any

from soc.similar.index import PURPOSE
from soc.store import BgeM3Embedder, Embedder, StoreError, VectorStore
from soc.store.config import read_settings
from soc.tools import services

SERVICE_NAME = "similar"
TOOL_NAME = "search_similar_cases"
logger = logging.getLogger("soc.similar")


@dataclass(frozen=True)
class SimilarService:
    """도구와 L1 색인이 함께 쓰는 임베더와 `ticket_verdicts` 저장소."""

    embedder: Embedder
    store: VectorStore


def build_service(config: dict[str, Any]) -> SimilarService | None:
    """도구를 허용했고 Qdrant 주소 환경변수가 있을 때만 만든다. 모델은 처음 쓸 때 올라간다.

    아니면 None. 설정이 틀렸거나 Qdrant 주소를 쓸 수 없는 경우도 None이고, 종류만 로그에 남긴다.
    """
    allowed = config.get("tools", {}).get("allowed", {})
    if not any(TOOL_NAME in allowed.get(stage, []) for stage in ("l1", "l2")):
        return None
    try:
        settings = read_settings(config["store"])
        embedder = BgeM3Embedder(settings.embedder)
        return SimilarService(embedder, VectorStore(PURPOSE, embedder, settings))
    except (StoreError, KeyError, ValueError) as exc:
        logger.warning("유사 사례 검색을 쓰지 않는다(%s)", type(exc).__name__)
        return None


def install_service(config: dict[str, Any]) -> SimilarService | None:
    """build_service로 만들어 도구 공유 객체로 등록한다."""
    service = build_service(config)
    if service is not None:
        services.install(SERVICE_NAME, service)
    return service
