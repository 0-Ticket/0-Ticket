"""L2 운영 CLI는 reindex만 제공하고 공개 건수·종료 코드만 낸다."""

from typing import Any

import pytest

from soc.l2 import __main__ as command
from soc.store import StoreError


def config() -> dict[str, Any]:
    return {
        "store": {
            "qdrant": {"url_env": "QDRANT_URL"},
            "embedder": {
                "model_id": "BAAI/bge-m3",
                "revision": "5617a9f61b028005a4858fdac845db406aefb181",
            },
        }
    }


def test_reindex_command_prints_counts_and_returns_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setenv("DATABASE_URL", "postgresql://not-printed")
    monkeypatch.setattr(command, "load_full_config", lambda: config())
    monkeypatch.setattr(command, "BgeM3Embedder", lambda settings: "embedder")
    monkeypatch.setattr(command, "VectorStore", lambda *args: "store")

    def run(database_url: str, embedder: Any, store: Any, *, recreate: bool) -> dict[str, int]:
        seen.update(database_url=database_url, embedder=embedder, store=store, recreate=recreate)
        return {"processed": 2, "succeeded": 2, "failed": 0}

    monkeypatch.setattr(command, "reindex", run)

    assert command.main(["reindex", "--recreate"]) == 0
    assert seen == {
        "database_url": "postgresql://not-printed",
        "embedder": "embedder",
        "store": "store",
        "recreate": True,
    }
    assert capsys.readouterr().out.strip() == "processed=2 succeeded=2 failed=0"


def test_reindex_command_returns_one_on_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://not-printed")
    monkeypatch.setattr(command, "load_full_config", lambda: config())
    monkeypatch.setattr(command, "BgeM3Embedder", lambda settings: "embedder")
    monkeypatch.setattr(command, "VectorStore", lambda *args: "store")
    monkeypatch.setattr(
        command,
        "reindex",
        lambda *args, **kwargs: {"processed": 1, "succeeded": 0, "failed": 1},
    )

    assert command.main(["reindex"]) == 1


def test_reindex_command_distinguishes_config_and_operation_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(command, "load_full_config", lambda: config())
    assert command.main(["reindex"]) == 2

    monkeypatch.setenv("DATABASE_URL", "postgresql://not-printed")
    monkeypatch.setattr(command, "VectorStore", lambda *args: (_ for _ in ()).throw(StoreError()))
    assert command.main(["reindex"]) == 1
