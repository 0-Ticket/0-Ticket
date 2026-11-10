"""L2 워커 생성은 시작할 때 컬렉션을 한 번 확인한다."""

from typing import Any

import pytest

from soc.l2.analyze import worker as analyze_worker
from soc.l2.branch import worker
from soc.store import CollectionMismatch, StoreError


def config() -> dict[str, Any]:
    return {
        "l2": {
            "branch": {
                "candidate_window_ms": 1000,
                "max_candidates": 5,
                "candidate_source": "vector",
                "top_k": 50,
            }
        },
        "store": {
            "qdrant": {"url_env": "QDRANT_URL"},
            "embedder": {
                "model_id": "BAAI/bge-m3",
                "revision": "5617a9f61b028005a4858fdac845db406aefb181",
            },
        },
    }


class FakeStore:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.ensured = 0

    def ensure_collection(self) -> None:
        self.ensured += 1
        if self.error is not None:
            raise self.error


def test_build_worker_ensures_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeStore()
    monkeypatch.setenv("DATABASE_URL", "postgresql://not-used")
    monkeypatch.setattr(worker, "BgeM3Embedder", lambda settings: "embedder")
    monkeypatch.setattr(worker, "VectorStore", lambda *args: store)

    built = worker.build_worker(config())

    assert built.stage == "l2"
    assert built.name == "l2_branch"
    assert store.ensured == 1


def test_build_worker_continues_after_general_store_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore(StoreError())
    monkeypatch.setenv("DATABASE_URL", "postgresql://not-used")
    monkeypatch.setattr(worker, "BgeM3Embedder", lambda settings: "embedder")
    monkeypatch.setattr(worker, "VectorStore", lambda *args: store)

    assert worker.build_worker(config()).name == "l2_branch"


def test_build_worker_rejects_collection_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeStore(CollectionMismatch())
    monkeypatch.setenv("DATABASE_URL", "postgresql://not-used")
    monkeypatch.setattr(worker, "BgeM3Embedder", lambda settings: "embedder")
    monkeypatch.setattr(worker, "VectorStore", lambda *args: store)

    with pytest.raises(CollectionMismatch):
        worker.build_worker(config())


def test_build_analyze_worker_reads_shared_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    full = config()
    full["l2"]["analyze"] = {
        "lookback_ms": 1000,
        "max_failures": 3,
        "failure_retry_cooldown_ms": 3_600_000,
        "max_seed_entities": 10,
        "max_related_per_entity": 20,
    }
    full["tools"] = {"max_range_days": 7}
    full["asset_lookup"] = {"statement_timeout_ms": 5000}
    full["l3"] = {"intel": {"attack": {"version": "20.0"}}}
    monkeypatch.setenv("DATABASE_URL", "postgresql://not-used")

    built = analyze_worker.build_worker(full)

    assert built.stage == "l2"
    assert built.name == "l2_analyze"
