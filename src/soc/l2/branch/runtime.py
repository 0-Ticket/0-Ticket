"""분류 색인과 분류 워커가 하나의 임베더를 공유한다."""

from dataclasses import dataclass
from functools import lru_cache

from soc.store import BgeM3Embedder, VectorStore
from soc.store.config import StoreSettings


@dataclass(frozen=True)
class BranchService:
    embedder: BgeM3Embedder
    store: VectorStore


@lru_cache(maxsize=1)
def get_service(settings: StoreSettings) -> BranchService:
    embedder = BgeM3Embedder(settings.embedder)
    return BranchService(embedder, VectorStore("ticket_branch", embedder, settings))
