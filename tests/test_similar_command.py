"""유사 사례 운영 CLI는 reindex만 제공하고 공개 건수·종료 코드만 낸다(#313)."""

from typing import Any

import pytest

from soc.similar import __main__ as command
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


def patch_common(monkeypatch: pytest.MonkeyPatch, seen: dict[str, Any] | None = None) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://not-printed")
    monkeypatch.setattr(command, "load_full_config", lambda: config())
    monkeypatch.setattr(command, "BgeM3Embedder", lambda settings: "embedder")

    def store(purpose: str, embedder: Any, settings: Any) -> str:
        if seen is not None:
            seen["purpose"] = purpose
        return "store"

    monkeypatch.setattr(command, "VectorStore", store)


def test_reindex_command_prints_counts_and_uses_the_ticket_verdicts_collection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, Any] = {}
    patch_common(monkeypatch, seen)

    def run(database_url: str, embedder: Any, store: Any, *, recreate: bool) -> dict[str, int]:
        seen.update(database_url=database_url, recreate=recreate)
        return {"processed": 3, "succeeded": 2, "skipped": 1, "failed": 0}

    monkeypatch.setattr(command, "reindex", run)

    assert command.main(["reindex", "--recreate"]) == 0
    assert seen == {
        "purpose": "ticket_verdicts",
        "database_url": "postgresql://not-printed",
        "recreate": True,
    }
    out = capsys.readouterr().out
    assert out.strip() == "processed=3 succeeded=2 skipped=1 failed=0"
    assert "not-printed" not in out  # 주소는 출력하지 않는다


def test_reindex_command_returns_one_on_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_common(monkeypatch)
    monkeypatch.setattr(
        command,
        "reindex",
        lambda *args, **kwargs: {"processed": 1, "succeeded": 0, "skipped": 0, "failed": 1},
    )

    assert command.main(["reindex"]) == 1


def test_reindex_command_distinguishes_config_and_operation_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(command, "load_full_config", lambda: config())
    assert command.main(["reindex"]) == 2

    patch_common(monkeypatch)
    monkeypatch.setattr(command, "VectorStore", lambda *args: (_ for _ in ()).throw(StoreError()))
    assert command.main(["reindex"]) == 1
    assert "not-printed" not in capsys.readouterr().err
