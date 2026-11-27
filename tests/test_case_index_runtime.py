"""L3 Case 검색 도구의 공유 객체: 만드는 조건, 워커와 같은 인스턴스, 설치 순서(#392, D-087)."""

import logging
import threading
from pathlib import Path
from typing import Any

import pytest
from test_agent_executor import FakeWorker

from soc.agent.executor import main
from soc.case_index import index
from soc.case_index.runtime import SERVICE_NAME, build_service, install_service
from soc.l2.branch import runtime as branch_runtime
from soc.store.config import read_settings
from soc.tools import services

TOOL = "search_confirmed_cases"
STORE = {
    "qdrant": {"url_env": "QDRANT_URL"},
    "embedder": {
        "model_id": "BAAI/bge-m3",
        "revision": "5617a9f61b028005a4858fdac845db406aefb181",
    },
}


def config(**allowed: list[str]) -> dict[str, Any]:
    return {"tools": {"allowed": allowed}, "store": STORE}


@pytest.fixture(autouse=True)
def fresh_caches():
    branch_runtime.get_service.cache_clear()
    index.get_store.cache_clear()
    yield
    branch_runtime.get_service.cache_clear()
    index.get_store.cache_clear()


def test_service_is_not_built_unless_the_tool_is_allowed_for_l3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")

    assert build_service(config(l1=[TOOL], l2=[TOOL], l3=["get_alert"])) is None
    assert install_service(config(l3=["get_alert"])) is None
    assert services.snapshot() == {}


@pytest.mark.parametrize(
    "allowed",
    [
        {"l3_hypothesize": [TOOL]},  # 태스크 키만 있는 배포 설정(D-086)
        {"l3_verify": [TOOL]},
        {"l3_hypothesize": [TOOL], "l3_verify": [TOOL]},
        {"l3": [TOOL]},  # 단계 키만 있는 설정은 그대로 동작한다
        {"l3_hypothesize": [], "l3": [TOOL]},  # 태스크 키가 없는 l3_verify는 단계 키를 본다
    ],
)
def test_service_is_built_when_an_l3_task_allows_the_tool(
    monkeypatch: pytest.MonkeyPatch, allowed: dict[str, list[str]]
) -> None:
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")

    assert build_service(config(**allowed)) is not None


@pytest.mark.parametrize(
    "allowed",
    [
        {"l1_alert_triage": [TOOL], "l2_investigate": [TOOL]},  # L3 태스크가 아니다
        {"l3_hypothesize": [], "l3_verify": [], "l3": [TOOL]},  # 두 태스크 키가 단계 키를 가린다
        {"l3_hypothesize": ["get_alert"]},
    ],
)
def test_service_is_not_built_when_no_l3_task_gets_the_tool(
    monkeypatch: pytest.MonkeyPatch, allowed: dict[str, list[str]]
) -> None:
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")

    assert build_service(config(**allowed)) is None


def test_the_default_config_installs_the_service(
    monkeypatch: pytest.MonkeyPatch, default_config_dir: Path
) -> None:
    """배포 기본 설정은 태스크 키만 쓴다. 그 설정에서 서비스가 설치돼야 도구가 보인다."""
    from soc.agent.config import load_full_config

    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")

    service = install_service(load_full_config(default_config_dir))

    assert service is not None
    assert services.snapshot()[SERVICE_NAME] is service


def test_service_is_not_built_without_the_qdrant_variable_and_logs_only_the_kind(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("QDRANT_URL", raising=False)

    with caplog.at_level(logging.WARNING):
        assert install_service(config(l3=[TOOL])) is None

    assert services.snapshot() == {}
    assert "StoreError" in caplog.text
    assert "QDRANT" not in caplog.text  # 환경변수 이름·값도 남기지 않는다


def test_missing_store_config_gives_no_service() -> None:
    assert build_service({"tools": {"allowed": {"l3": [TOOL]}}}) is None


def test_service_shares_the_embedder_and_the_store_with_the_index_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")

    service = install_service(config(l3=[TOOL]))

    assert service is not None
    assert services.snapshot()[SERVICE_NAME] is service
    settings = read_settings(STORE)
    # 색인 워커가 쓰는 것과 같은 인스턴스다. 상주 모델이 늘지 않는다(약 2.27GB)
    assert service.embedder is index.get_embedder(settings)
    assert service.embedder is branch_runtime.get_service(settings).embedder
    assert service.store is index.get_store(settings)
    assert service.store.collection.startswith("confirmed_cases")


def test_main_installs_the_case_service_before_the_workers_are_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    (tmp_path / "default.toml").write_text(
        "[executor]\nshutdown_timeout_seconds = 5\n"
        "[executor.l1]\ninterval_seconds = 0.01\npoll_limit = 1\nworkers = ['soc.test:a']\n"
        "[executor.l2]\ninterval_seconds = 0\npoll_limit = 1\nworkers = []\n"
        "[executor.l3]\ninterval_seconds = 0\npoll_limit = 1\nworkers = []\n"
        f"[tools.allowed]\nl3 = ['{TOOL}']\n"
        "[store.qdrant]\nurl_env = 'QDRANT_URL'\n"
        "[store.embedder]\nmodel_id = 'BAAI/bge-m3'\n"
        "revision = '5617a9f61b028005a4858fdac845db406aefb181'\n",
        encoding="utf-8",
    )
    seen: list[set[str]] = []
    worker = FakeWorker("l1", "a", [])

    def resolve(path: str) -> Any:
        def factory(_config: Any) -> FakeWorker:
            seen.append(set(services.snapshot()))
            return worker

        return factory

    stop = threading.Event()
    threading.Timer(0.1, stop.set).start()

    assert main([], config_dir=tmp_path, stop_event=stop, resolve=resolve) == 0
    assert seen == [{SERVICE_NAME}]
