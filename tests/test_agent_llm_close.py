"""run_agent가 만든 LLM 클라이언트는 어떻게 끝나든 닫힌다(#280 C8). 네트워크 없이 돈다.

build_client를 가짜 전송 계층(httpx2.MockTransport)을 넣는 것으로 바꿔 run_agent를 여러 번
부르고, 만든 클라이언트가 모두 닫혔는지 본다.
"""

import asyncio
import json
import logging
import threading
from typing import Any

import httpx2
import pytest
from test_agent_core import ALERT_ID, CONFIG, make_task
from test_agent_llm import FAKE_KEY, PROVIDERS, _completion, llm_config

from soc.agent import llm, run_agent, runner
from soc.agent.agent_log import MemoryLogSink
from soc.agent.executor import _cancel_all

VERDICT = {"decision": "benign", "confidence": 0.9, "reason": "테스트", "evidence_ids": [ALERT_ID]}
OK = _completion(json.dumps(VERDICT))


def config() -> dict[str, Any]:
    cfg = llm_config(**PROVIDERS["foundry"])
    cfg["tools"] = {**CONFIG["tools"], "allowed": {"l1": [], "l2": [], "l3": []}}
    return cfg


class Clients:
    """run_agent가 만든 클라이언트를 모아 두고, 요청마다 handler로 답한다."""

    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self.made: list[Any] = []
        self.requests = 0

    def build(self, cfg: Any, environ: Any = None, http_client: Any = None) -> Any:
        def counted(request: httpx2.Request) -> Any:
            self.requests += 1
            return self.handler(request)

        client, name = llm.build_client(
            cfg,
            environ={"LLM_API_KEY": FAKE_KEY},
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(counted)),
        )
        self.made.append(client)
        return client, name

    @property
    def open(self) -> list[Any]:
        return [c for c in self.made if not c.is_closed()]


@pytest.fixture
def agent(monkeypatch: pytest.MonkeyPatch):
    sink = MemoryLogSink()
    monkeypatch.setenv("DATABASE_URL", "postgresql://soc@127.0.0.1:1/soc")
    monkeypatch.setattr("soc.agent.runner.PostgresLogSink", lambda *a, **k: sink)
    monkeypatch.setattr("soc.agent.runner.load_config", config)

    def install(handler: Any) -> Clients:
        clients = Clients(handler)
        monkeypatch.setattr("soc.agent.runner.build_client", clients.build)
        return clients

    return install


def answer(status: int = 200, body: Any = OK):
    return lambda request: httpx2.Response(status, json=body, headers={})


def test_build_model_still_returns_model_and_name() -> None:
    model, name = llm.build_model(config(), environ={"LLM_API_KEY": FAKE_KEY})
    assert name == PROVIDERS["foundry"]["model"]
    assert model is not None


def test_many_runs_leave_no_open_client(agent: Any) -> None:
    clients = agent(answer())
    results = [run_agent(make_task()) for _ in range(5)]
    assert [r.ok for r in results] == [True] * 5
    assert len(clients.made) == 5  # run마다 하나
    assert clients.requests == 5
    assert clients.open == []


def test_failed_runs_close_the_client(agent: Any) -> None:
    clients = agent(answer(200, _completion('{"decision": "undetermined"}')))  # 계약 위반
    result = run_agent(make_task())
    assert result.failure == "format_error"
    assert clients.open == []

    clients = agent(answer(401, {"error": {"message": "invalid api key"}}))
    assert run_agent(make_task()).failure == "provider_error"
    assert clients.open == []

    clients = agent(answer(429, {"error": {}}))
    assert run_agent(make_task()).failure == "rate_limited"
    assert clients.open == []


def test_run_that_fails_before_start_closes_the_client(
    agent: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    clients = agent(answer())

    real = runner.build_redactor

    def broken(config: Any) -> Any:
        if config:  # 시작 전 실패 줄을 쓰는 기본 설정({})에서는 준비된다
            raise RuntimeError("가림 준비 실패(테스트)")
        return real(config)

    monkeypatch.setattr("soc.agent.runner.build_redactor", broken)
    result = run_agent(make_task())
    assert result.failure == "provider_error"
    assert clients.requests == 0  # 모델을 부르지 않았다
    assert len(clients.made) == 1 and clients.open == []


def test_tool_config_error_before_start_closes_the_client(
    agent: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    clients = agent(answer())
    cfg = config()
    cfg["tools"] = {**cfg["tools"], "allowed": {"l1": ["no_such_tool"], "l2": [], "l3": []}}
    monkeypatch.setattr("soc.agent.runner.load_config", lambda: cfg)
    result = run_agent(make_task())
    assert result.failure == "provider_error"
    assert clients.open == []


def test_cancelled_run_closes_the_client(agent: Any) -> None:
    started = threading.Event()

    async def hang(request: httpx2.Request) -> httpx2.Response:
        started.set()
        await asyncio.sleep(60)
        raise AssertionError("취소돼야 한다")

    clients = agent(hang)
    box: dict[str, Any] = {}

    def stage() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        box["loop"] = loop
        try:
            box["result"] = run_agent(make_task())
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    thread = threading.Thread(target=stage, daemon=True)
    thread.start()
    assert started.wait(5)
    box["loop"].call_soon_threadsafe(_cancel_all, box["loop"])
    thread.join(10)
    assert not thread.is_alive()
    assert box["result"].failure == "cancelled"
    assert len(clients.made) == 1 and clients.open == []


def test_close_failure_does_not_raise_and_logs_only_the_kind(
    agent: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    clients = agent(answer())
    original = llm.build_client

    class Broken:
        def __init__(self, client: Any) -> None:
            self._client = client

        def __getattr__(self, name: str) -> Any:
            return getattr(self._client, name)

        async def close(self) -> None:
            raise RuntimeError("닫기 실패 메시지(테스트)")

    def build(cfg: Any, environ: Any = None, http_client: Any = None) -> Any:
        client, name = original(
            cfg,
            environ={"LLM_API_KEY": FAKE_KEY},
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(answer())),
        )
        clients.made.append(client)
        return Broken(client), name

    monkeypatch.setattr("soc.agent.runner.build_client", build)
    with caplog.at_level(logging.WARNING, logger="soc.agent.runner"):
        result = run_agent(make_task())
    assert result.ok
    assert "RuntimeError" in caplog.text and "닫기 실패 메시지" not in caplog.text
