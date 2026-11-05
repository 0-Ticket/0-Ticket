"""Qdrant 벡터 저장소(#257, Qdrant D-013).

L2·L3가 함께 쓰는 일반 연산만 둔다. Ticket·Incident·Case 같은 업무 개념은 넣지 않는다.
PostgreSQL이 권위 원본이고 여기 들어가는 것은 파생 색인이다(#248).

주소는 설정에 두지 않고 환경변수(기본 QDRANT_URL)로만 읽는다. 오류 메시지에는 환경변수 이름만
남기고 주소 값은 넣지 않는다.
"""

import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from qdrant_client import QdrantClient, models

from soc.store.config import QdrantSettings, StoreSettings
from soc.store.embedder import Embedder, collection_name

# payload 필터가 받는 값의 종류. 동등 조건만 지원한다.
FilterValue = str | int | bool


class StoreError(Exception):
    """환경변수·주소·접속 실패와 그 밖의 Qdrant 실패."""


class CollectionMissing(StoreError):
    """컬렉션이 아직 없다. 부르는 쪽이 직접 조회로 떨어질 수 있다(#248)."""


class CollectionMismatch(StoreError):
    """있는 컬렉션의 vector 모양·차원·거리 방식이 지금 설정과 다르다.

    설정 오류라 fallback하지 않고 그대로 끝낸다(#248).
    """


@dataclass(frozen=True)
class SearchHit:
    """검색 결과 한 건.

    필드:
        point_id: UUID 문자열.
        score: Cosine 유사도. 클수록 가깝다.
        payload: 저장한 payload. 밖에서 온 문자열이 있을 수 있어 데이터로만 다룬다.
    """

    point_id: str
    score: float
    payload: dict[str, Any]


def create_client(settings: QdrantSettings, **kwargs: Any) -> QdrantClient:
    """환경변수에서 주소를 읽어 Qdrant 클라이언트를 만든다.

    인자:
        settings: url_env를 담은 [store.qdrant] 값.
        kwargs: QdrantClient에 그대로 넘길 값(예: timeout).

    발생:
        StoreError: 환경변수가 없거나 비었거나, http(s) 주소가 아닐 때.
    """
    name = settings.url_env
    url = os.environ.get(name, "").strip()
    if not url:
        raise StoreError(f"환경변수 {name}이 없다")
    parsed = urlparse(url)
    # 주소 값은 오류에 넣지 않는다. 계정 정보가 들어 있을 수 있다.
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise StoreError(f"환경변수 {name}은 http(s) Qdrant 주소여야 한다")
    try:
        return QdrantClient(url=url, **kwargs)
    except Exception as error:
        raise StoreError(f"환경변수 {name}의 Qdrant에 연결하지 못했다") from error


def build_filter(filters: dict[str, FilterValue]) -> models.Filter:
    """payload 동등 조건을 AND로 묶은 Qdrant 필터를 만든다.

    인자:
        filters: payload 키와 값. 값은 문자열·정수·불리언만 받는다. 빈 표는 받지 않는다.

    발생:
        ValueError: 키가 빈 문자열이거나 값의 종류가 맞지 않을 때(부르는 코드의 잘못이다).
    """
    if not filters:
        raise ValueError("필터가 비어 있다")
    must = []
    for key, value in filters.items():
        if not isinstance(key, str) or not key:
            raise ValueError("필터 키는 빈 값이 아닌 문자열이어야 한다")
        if not isinstance(value, str | int | bool):
            raise ValueError(f"필터 {key}의 값은 문자열·정수·불리언이어야 한다")
        must.append(models.FieldCondition(key=key, match=models.MatchValue(value=value)))
    return models.Filter(must=must)


@contextmanager
def _wrapped(message: str, collection: str | None = None) -> Iterator[None]:
    """Qdrant 호출의 실패를 공개 오류 세 종류로 바꾼다.

    인자:
        message: StoreError에 넣을 설명. 주소 값은 넣지 않는다.
        collection: 주면 "없는 컬렉션" 실패를 CollectionMissing으로 바꾼다.
    """
    try:
        yield
    except StoreError:
        raise
    except Exception as error:
        # qdrant-client는 없는 컬렉션을 404 또는 gRPC NOT_FOUND로 알려 준다. 종류가
        # 버전마다 달라 본문으로 가린다(UnexpectedResponse, RpcError 모두 같은 문장을 담는다).
        if collection is not None and _is_missing(error, collection):
            raise CollectionMissing(f"컬렉션 {collection}이 없다") from error
        raise StoreError(message) from error


def _is_missing(error: Exception, collection: str) -> bool:
    """오류가 "그 컬렉션이 없다"는 뜻인지 본다."""
    text = str(error).lower()
    return f"collection `{collection}` doesn't exist" in text or (
        "not found" in text and collection.lower() in text
    )


class VectorStore:
    """용도 하나의 컬렉션을 다루는 저장소.

    컬렉션 이름은 용도·모델 ID·revision·ONNX 파일에서 파생한다. 모델이나 revision을 바꾸면
    다른 컬렉션이 되고, 쓰지 않게 된 옛 컬렉션은 사람이 Qdrant에서 직접 지운다(#257).
    """

    def __init__(
        self,
        purpose: str,
        embedder: Embedder,
        settings: StoreSettings,
        client: QdrantClient | None = None,
    ) -> None:
        """인자 purpose는 코드 상수다([a-z0-9_] 1~64자). client가 없으면 환경변수로 만든다."""
        self._collection = collection_name(purpose, settings.embedder)
        self._embedder = embedder
        self._client = client if client is not None else create_client(settings.qdrant)

    @property
    def collection(self) -> str:
        """이 저장소가 쓰는 컬렉션 이름."""
        return self._collection

    def exists(self) -> bool:
        """컬렉션이 있으면 True. 접속 실패는 StoreError다."""
        with _wrapped("컬렉션을 확인하지 못했다"):
            return self._client.collection_exists(self._collection)

    def ensure_collection(self) -> None:
        """컬렉션이 없으면 임베더 차원과 Cosine으로 만든다.

        이미 있으면 vector 모양·차원·거리 방식만 확인하고 아무것도 바꾸지 않는다.

        발생:
            CollectionMismatch: 있는 컬렉션이 지금 설정과 다를 때.
            StoreError: 그 밖의 Qdrant 실패.
        """
        if self.exists():
            self._check_existing()
            return
        with _wrapped("컬렉션을 만들지 못했다"):
            self._client.create_collection(
                self._collection,
                vectors_config=models.VectorParams(
                    size=self._embedder.dimension, distance=models.Distance.COSINE
                ),
            )

    def upsert(self, point_id: str, vector: Sequence[float], payload: dict[str, Any]) -> None:
        """point 한 건을 넣거나 덮어쓴다. Qdrant 처리가 끝난 뒤 돌아온다.

        인자:
            point_id: UUID 문자열.
            vector: 임베더 차원과 길이가 같은 벡터.
            payload: 함께 저장할 값.

        발생:
            ValueError: 벡터 길이가 임베더 차원과 다를 때.
            CollectionMissing: 컬렉션이 없을 때.
            StoreError: 그 밖의 Qdrant 실패.
        """
        self._check_vector(vector)
        point = models.PointStruct(id=point_id, vector=list(vector), payload=payload)
        with _wrapped("point를 저장하지 못했다", self._collection):
            self._client.upsert(self._collection, points=[point], wait=True)

    def search(
        self,
        vector: Sequence[float],
        top_k: int,
        filters: dict[str, FilterValue] | None = None,
    ) -> tuple[SearchHit, ...]:
        """벡터로 가까운 point를 찾는다. filters가 있으면 payload 동등 조건 AND로 좁힌다.

        인자:
            vector: 임베더 차원과 길이가 같은 질의 벡터.
            top_k: 받을 결과 수. 1 이상이어야 한다.
            filters: payload 동등 조건. None이면 걸지 않는다.

        반환:
            점수가 높은 순서의 SearchHit. payload는 데이터로만 다룬다.

        발생:
            ValueError: 벡터 길이·top_k·필터가 올바르지 않을 때.
            CollectionMissing: 컬렉션이 없을 때.
            StoreError: 그 밖의 Qdrant 실패.
        """
        self._check_vector(vector)
        if top_k < 1:
            raise ValueError("top_k는 1 이상이어야 한다")
        condition = build_filter(filters) if filters else None
        with _wrapped("검색하지 못했다", self._collection):
            found = self._client.query_points(
                self._collection,
                query=list(vector),
                limit=top_k,
                query_filter=condition,
                with_payload=True,
            ).points
        return tuple(
            SearchHit(point_id=str(p.id), score=float(p.score), payload=dict(p.payload or {}))
            for p in found
        )

    def delete_by_payload(self, key: str, value: FilterValue) -> None:
        """payload 키·값이 맞는 point를 모두 지운다. Qdrant 처리가 끝난 뒤 돌아온다.

        발생:
            ValueError: 키·값이 올바르지 않을 때.
            CollectionMissing: 컬렉션이 없을 때.
            StoreError: 그 밖의 Qdrant 실패.
        """
        condition = build_filter({key: value})
        with _wrapped("point를 지우지 못했다", self._collection):
            self._client.delete(
                self._collection,
                points_selector=models.FilterSelector(filter=condition),
                wait=True,
            )

    def drop_collection(self) -> None:
        """지금 설정에서 파생한 컬렉션을 지운다. 없으면 아무것도 하지 않는다."""
        with _wrapped("컬렉션을 지우지 못했다"):
            self._client.delete_collection(self._collection)

    def _check_vector(self, vector: Sequence[float]) -> None:
        dimension = self._embedder.dimension
        if len(vector) != dimension:
            raise ValueError(f"벡터 길이가 {dimension}이 아니다: {len(vector)}")

    def _check_existing(self) -> None:
        """있는 컬렉션이 지금 임베더·거리 방식과 맞는지 본다."""
        with _wrapped("컬렉션 정보를 읽지 못했다", self._collection):
            vectors = self._client.get_collection(self._collection).config.params.vectors
        # 이름 있는 vector면 표로 온다. 이 계층은 unnamed 하나만 쓴다.
        if not isinstance(vectors, models.VectorParams):
            raise CollectionMismatch(f"{self._collection}은 unnamed vector 하나를 쓰지 않는다")
        if vectors.size != self._embedder.dimension:
            raise CollectionMismatch(
                f"{self._collection}의 벡터 차원이 {self._embedder.dimension}이 아니다"
            )
        if vectors.distance != models.Distance.COSINE:
            raise CollectionMismatch(f"{self._collection}의 거리 방식이 Cosine이 아니다")
