"""동기 도구 핸들러의 데몬 스레드 실행과 취소(#280 C4). DB·ELK에 접속하지 않는다.

느린 가짜 DB(psycopg.connect를 이벤트로 막는다)와 느린 가짜 SIEM(MockTransport 처리기를 이벤트로
막는다)이 도는 중에 실행기와 같은 방식(단계 스레드 루프에 _cancel_all)으로 취소를 보낸다.
막힌 스레드는 테스트 끝에 풀어 준다.
"""

import asyncio
import logging
import re
import threading
import time
from typing import Any

import httpx
import psycopg
import pytest
from fake_model import FakeModel
from fake_siem import ELK_KEY, ELK_URL
from test_agent_core import ALERT_ID, CONFIG, make_task, no_sleep
from test_tools_registry import config as registry_config
from test_tools_registry import spec
from test_tools_siem import END, START
from test_tools_siem import config as siem_config
from tool_helpers import Caller, parse

from soc.agent.agent_log import MemoryLogSink
from soc.agent.executor import _cancel_all
from soc.agent.runner import run_task
from soc.tools import ToolRegistry, default_registry
from soc.tools.siem import siem_tools

LIMIT = 1.5  # 취소를 보낸 뒤 run이 끝나야 하는 최대 초. 막힌 도구는 이보다 오래 막혀 있다
BLOCK = 10.0
WARN = re.compile(r"취소로 버려진 도구 스레드: tool=(\w+) elapsed=\d+\.\ds")


class Blocked:
    """도구 안에서 막혀 있는 스레드를 풀고 상태를 보는 도구."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def block(self) -> None:
        self.entered.set()
        self.release.wait(BLOCK)


@pytest.fixture
def blocked():
    b = Blocked()
    yield b
    b.release.set()  # 막힌 데몬 스레드를 남기지 않는다


def run_and_cancel(
    registry: ToolRegistry,
    cfg: dict[str, Any],
    blocked: Blocked,
    name: str,
    arguments: dict[str, Any],
) -> tuple[Any, float, list[threading.Thread]]:
    """단계 스레드처럼 run_task를 돌리다가, 도구가 막히면 취소를 보낸다.

    (결과, 취소를 보낸 뒤 끝나기까지 초, 취소 직전에 살아 있던 도구 스레드)
    """
    model = FakeModel({"steps": [{"tool_call": {"name": name, "arguments": arguments}}]})
    box: dict[str, Any] = {}

    def stage() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        box["loop"] = loop
        try:
            box["result"] = run_task(
                make_task(),
                model=model,
                model_name="fake",
                log_sink=MemoryLogSink(),
                config=cfg,
                registry=registry,
                sleep=no_sleep,
            )
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    thread = threading.Thread(target=stage, daemon=True)
    thread.start()
    assert blocked.entered.wait(5), "도구가 시작되지 않았다"
    tool_threads = [t for t in threading.enumerate() if t.name.startswith("soc-tool-")]
    time.sleep(0.05)
    sent = time.monotonic()
    box["loop"].call_soon_threadsafe(_cancel_all, box["loop"])
    thread.join(BLOCK)
    elapsed = time.monotonic() - sent
    assert not thread.is_alive()
    return box["result"], elapsed, tool_threads


def db_setup(
    monkeypatch: pytest.MonkeyPatch, blocked: Blocked
) -> tuple[ToolRegistry, dict[str, Any]]:
    monkeypatch.setenv("AGENT_DATABASE_URL", "postgresql://reader@127.0.0.1:1/soc")

    def slow_connect(*args: Any, **kwargs: Any) -> Any:
        blocked.block()
        raise psycopg.OperationalError("연결 실패(테스트)")

    monkeypatch.setattr(psycopg, "connect", slow_connect)
    cfg = registry_config(["get_alert"])
    cfg["tools"] = {**CONFIG["tools"], "allowed": {"l1": ["get_alert"], "l2": [], "l3": []}}
    return default_registry(), cfg


def siem_setup(
    monkeypatch: pytest.MonkeyPatch, blocked: Blocked
) -> tuple[ToolRegistry, dict[str, Any]]:
    monkeypatch.setenv("ELK_URL", ELK_URL)
    monkeypatch.setenv("ELK_API_KEY", ELK_KEY)

    def slow(request: httpx.Request) -> httpx.Response:
        blocked.block()
        return httpx.Response(200, json={})

    return ToolRegistry(siem_tools(transport=httpx.MockTransport(slow))), siem_config()


DB_CALL = ("get_alert", {"id": ALERT_ID})
SIEM_CALL = ("query_siem", {"target": "web_access", "start_ms": START, "end_ms": END})


@pytest.mark.parametrize(
    ("setup", "call"), [(db_setup, DB_CALL), (siem_setup, SIEM_CALL)], ids=["db", "siem"]
)
def test_cancel_during_slow_tool_ends_cancelled_within_the_limit(
    setup: Any, call: Any, blocked: Blocked, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, cfg = setup(monkeypatch, blocked)
    result, elapsed, _ = run_and_cancel(registry, cfg, blocked, *call)
    assert result.failure == "cancelled"
    assert elapsed < LIMIT  # 도구는 아직 막혀 있다(BLOCK초)
    assert not blocked.release.is_set()


@pytest.mark.parametrize(
    ("setup", "call"), [(db_setup, DB_CALL), (siem_setup, SIEM_CALL)], ids=["db", "siem"]
)
def test_tool_runs_on_a_daemon_thread_that_does_not_block_exit(
    setup: Any, call: Any, blocked: Blocked, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, cfg = setup(monkeypatch, blocked)
    _, _, tool_threads = run_and_cancel(registry, cfg, blocked, *call)
    assert len(tool_threads) == 1
    assert tool_threads[0].daemon
    assert tool_threads[0].name == f"soc-tool-{call[0]}"


def test_abandoned_tool_thread_leaves_one_warning_with_tool_name_and_elapsed_only(
    blocked: Blocked, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    registry, cfg = db_setup(monkeypatch, blocked)
    with caplog.at_level(logging.WARNING, logger="soc.agent.executor"):
        run_and_cancel(registry, cfg, blocked, "get_alert", {"id": ALERT_ID})
    warnings = [r for r in caplog.records if r.name == "soc.agent.executor"]
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING
    message = warnings[0].getMessage()
    assert WARN.fullmatch(message)
    assert warnings[0].exc_info is None  # 예외 메시지도 트레이스백도 없다
    for leak in (ALERT_ID, "reader", "127.0.0.1", "OperationalError", "연결 실패"):
        assert leak not in message


def test_siem_abandoned_warning_has_no_arguments_or_url(
    blocked: Blocked, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    registry, cfg = siem_setup(monkeypatch, blocked)
    with caplog.at_level(logging.WARNING, logger="soc.agent.executor"):
        run_and_cancel(registry, cfg, blocked, *SIEM_CALL)
    messages = [r.getMessage() for r in caplog.records if r.name == "soc.agent.executor"]
    assert len(messages) == 1
    match = WARN.fullmatch(messages[0])
    assert match and match.group(1) == "query_siem"
    for leak in ("elk.example.com", ELK_KEY, "web_access", str(START)):
        assert leak not in messages[0]


def test_no_warning_when_the_call_finishes_normally(caplog: pytest.LogCaptureFixture) -> None:
    ran: list[str] = []

    def handler(args: dict[str, Any], ctx: Any) -> list[dict[str, Any]]:
        ran.append(threading.current_thread().name)
        return [{"id": "alt_01a19f93-1150-7000-8000-000000000001"}]

    caller = Caller(ToolRegistry([spec("quick", handler)]), registry_config(["quick"]))
    with caplog.at_level(logging.DEBUG, logger="soc.agent.executor"):
        out = asyncio.run(caller("quick", {}))
    assert parse(out)["records"]
    assert ran == ["soc-tool-quick"]
    assert [r for r in caplog.records if r.name == "soc.agent.executor"] == []


def test_sync_handler_runs_off_the_loop_thread_and_async_handler_on_it() -> None:
    seen: dict[str, str] = {}
    loop_thread = threading.current_thread().name

    def sync_handler(args: dict[str, Any], ctx: Any) -> list[dict[str, Any]]:
        seen["sync"] = threading.current_thread().name
        return []

    async def async_handler(args: dict[str, Any], ctx: Any) -> list[dict[str, Any]]:
        seen["async"] = threading.current_thread().name
        return []

    registry = ToolRegistry([spec("s", sync_handler), spec("a", async_handler)])
    caller = Caller(registry, registry_config(["s", "a"]))
    asyncio.run(caller("s", {}))
    asyncio.run(caller("a", {}))
    assert seen["sync"] == "soc-tool-s"
    assert seen["async"] == loop_thread


def test_sync_handler_returning_an_awaitable_is_awaited_on_the_loop() -> None:
    seen: dict[str, str] = {}

    async def later() -> list[dict[str, Any]]:
        seen["awaited"] = threading.current_thread().name
        return [{"id": "alt_01a19f93-1150-7000-8000-000000000001"}]

    def handler(args: dict[str, Any], ctx: Any) -> Any:
        return later()

    caller = Caller(ToolRegistry([spec("t", handler)]), registry_config(["t"]))
    out = asyncio.run(caller("t", {}))
    assert parse(out)["records"]
    assert seen["awaited"] == threading.current_thread().name


def test_cancelled_call_writes_no_tool_result_or_ledger_entry(
    blocked: Blocked, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, cfg = db_setup(monkeypatch, blocked)
    sink_rows: list[Any] = []

    class Recorder:
        def tool_log_id(self, tool_call_id: str) -> str:
            return "agl_01a19f93-1150-7000-8000-0000000000aa"

        def report_tool(self, *args: Any, **kwargs: Any) -> None:
            sink_rows.append(args)

    session = registry.session(stage="l1", config=cfg, recorder=Recorder())
    box: dict[str, Any] = {}

    def stage() -> None:
        loop = asyncio.new_event_loop()
        box["loop"] = loop
        box["task"] = loop.create_task(session.invoke("get_alert", f'{{"id": "{ALERT_ID}"}}', "c1"))
        try:
            loop.run_until_complete(box["task"])
        except asyncio.CancelledError:
            box["cancelled"] = True
        finally:
            loop.close()

    thread = threading.Thread(target=stage, daemon=True)
    thread.start()
    assert blocked.entered.wait(5)
    box["loop"].call_soon_threadsafe(_cancel_all, box["loop"])
    thread.join(LIMIT)
    assert not thread.is_alive()
    assert box.get("cancelled")
    assert sink_rows == []
    assert session.evidence_ids == set()
