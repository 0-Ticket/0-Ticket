"""유사 사례 검색 텍스트와 실행 시작 때 만드는 공유 객체(#313, D-053)."""

import pytest

from soc.similar.runtime import SERVICE_NAME, build_service, install_service
from soc.similar.text import similar_text
from soc.tools import services


def test_text_is_alert_titles_in_order_without_duplicates() -> None:
    text = similar_text(["SQL injection on login", " SQL injection on login ", "Port scan"])

    assert text == "SQL injection on login\nPort scan"


def test_text_falls_back_to_hunt_hypothesis_only_without_alert_titles() -> None:
    assert similar_text([], "DNS beaconing") == "DNS beaconing"
    assert similar_text(["Port scan"], "DNS beaconing") == "Port scan"
    assert similar_text(["  ", ""], None) == ""


STORE = {
    "qdrant": {"url_env": "QDRANT_URL"},
    "embedder": {
        "model_id": "BAAI/bge-m3",
        "revision": "5617a9f61b028005a4858fdac845db406aefb181",
    },
}


def config(**allowed: list[str]) -> dict:
    return {"tools": {"allowed": allowed}, "store": STORE}


def test_service_is_not_built_unless_the_tool_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")

    assert build_service(config(l1=["get_alert"], l2=[], l3=["search_similar_cases"])) is None


def test_service_is_not_built_without_the_qdrant_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QDRANT_URL", raising=False)

    assert build_service(config(l1=["search_similar_cases"])) is None
    assert services.snapshot() == {}
    assert install_service(config(l1=["search_similar_cases"])) is None
    assert services.snapshot() == {}


def test_service_is_built_lazily_and_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")

    service = install_service(config(l2=["search_similar_cases"]))

    assert service is not None
    assert services.snapshot()[SERVICE_NAME] is service
    # 모델은 처음 쓸 때 올린다. 만들기만 했으므로 내려받지 않았다
    assert service.store.collection.startswith("ticket_verdicts")


def test_missing_store_config_gives_no_service() -> None:
    assert build_service({"tools": {"allowed": {"l1": ["search_similar_cases"]}}}) is None
