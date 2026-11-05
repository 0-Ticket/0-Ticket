"""벡터 저장소와 임베딩 계층(#257).

L2·L3가 함께 쓰는 공통 계층이다. 업무 개념(Ticket·Incident·Case)과 분류 로직은 부르는 쪽에 둔다.
"""

from soc.store.config import (
    ConfigError,
    EmbedderSettings,
    QdrantSettings,
    StoreSettings,
    load_config,
    read_settings,
)
from soc.store.embedder import (
    DIMENSION,
    MAX_TOKENS,
    ONNX_FILE,
    BgeM3Embedder,
    Embedder,
    OnnxOutput,
    collection_name,
)
from soc.store.qdrant import (
    CollectionMismatch,
    CollectionMissing,
    SearchHit,
    StoreError,
    VectorStore,
    build_filter,
    create_client,
)

__all__ = [
    "DIMENSION",
    "MAX_TOKENS",
    "ONNX_FILE",
    "BgeM3Embedder",
    "CollectionMismatch",
    "CollectionMissing",
    "ConfigError",
    "Embedder",
    "EmbedderSettings",
    "OnnxOutput",
    "QdrantSettings",
    "SearchHit",
    "StoreError",
    "StoreSettings",
    "VectorStore",
    "build_filter",
    "collection_name",
    "create_client",
    "load_config",
    "read_settings",
]
