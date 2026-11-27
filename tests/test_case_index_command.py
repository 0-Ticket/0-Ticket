"""Case 색인 운영 CLI는 건수와 예외 이름만 내고 종료 코드로 상태를 알린다(#391).

실제 점검·재색인은 test_case_index_db.py에서 본다. 여기서는 명령의 껍데기만 가짜로 확인한다.
"""

from typing import Any

import pytest

from soc.case_index import __main__ as command


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
    monkeypatch.setattr(command, "load_config", lambda: config())
    monkeypatch.setattr(command, "BgeM3Embedder", lambda settings: "embedder")

    def store(purpose: str, embedder: Any, settings: Any) -> str:
        if seen is not None:
            seen["purpose"] = purpose
        return "store"

    monkeypatch.setattr(command, "VectorStore", store)


def test_check_prints_the_counts_and_exits_zero_when_nothing_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, Any] = {}
    patch_common(monkeypatch, seen)
    monkeypatch.setattr(
        command,
        "check",
        lambda url, store: {"cases": 3, "missing": 0, "no_job": 0, "pending": 0, "no_artifact": 1},
    )

    assert command.main(["check"]) == 0
    assert seen["purpose"] == "confirmed_cases"
    out = capsys.readouterr().out
    assert out.strip() == "cases=3 missing=0 no_job=0 pending=0 no_artifact=1"
    assert "not-printed" not in out  # 주소는 출력하지 않는다


@pytest.mark.parametrize("key", ["missing", "no_job", "pending"])
def test_check_exits_one_for_each_kind_of_gap_but_not_for_no_artifact(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    patch_common(monkeypatch)
    counts = {"cases": 3, "missing": 0, "no_job": 0, "pending": 0, "no_artifact": 0}
    monkeypatch.setattr(command, "check", lambda url, store: {**counts, key: 1})
    assert command.main(["check"]) == 1

    monkeypatch.setattr(command, "check", lambda url, store: {**counts, "no_artifact": 3})
    assert command.main(["check"]) == 0


def test_reindex_passes_recreate_and_prints_counts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch_common(monkeypatch)
    seen: dict[str, Any] = {}

    def run(url: str, embedder: Any, store: Any, *, recreate: bool) -> dict[str, int]:
        seen["recreate"] = recreate
        return {"processed": 3, "succeeded": 3, "failed": 0}

    monkeypatch.setattr(command, "reindex", run)

    assert command.main(["reindex", "--recreate"]) == 0
    assert seen == {"recreate": True}
    assert capsys.readouterr().out.strip() == "processed=3 succeeded=3 failed=0"
    assert command.main(["reindex"]) == 0
    assert seen == {"recreate": False}


def test_reindex_exits_one_when_a_case_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_common(monkeypatch)
    monkeypatch.setattr(
        command, "reindex", lambda *a, **k: {"processed": 2, "succeeded": 1, "failed": 1}
    )
    assert command.main(["reindex"]) == 1


def test_config_errors_exit_two_and_operation_errors_print_only_the_exception_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(command, "load_config", lambda: config())
    assert command.main(["check"]) == 2

    patch_common(monkeypatch)

    def boom(url: str, store: Any) -> dict[str, int]:
        raise RuntimeError("http://qdrant.example:6333 secret title")

    monkeypatch.setattr(command, "check", boom)
    assert command.main(["check"]) == 1
    err = capsys.readouterr().err
    assert "RuntimeError" in err
    assert "qdrant.example" not in err and "secret title" not in err and "not-printed" not in err
