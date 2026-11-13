"""실행기의 예외 분류·죽은 단계 감지(C6)와 라운드 지표 로그(C7)(#280).

DB 없이 가짜 워커로 본다. 로그와 stderr에는 예외 종류만 남고 메시지는 남지 않는다.
"""

import asyncio
import logging
import re
import threading
import time
from typing import Any

import pytest
from test_agent_executor import WAIT, FakeWorker, start, wait_until

SECRET = "공격자가 쓴 문장일 수 있는 메시지"
ROUND = re.compile(
    r"round stage=(?P<stage>\w+) worker=(?P<worker>\w+) polled=(?P<polled>\d+)"
    r" limit=(?P<limit>\d+) handled=(?P<handled>\d+) failed=(?P<failed>\d+)"
    r" total_ms=(?P<total>\d+) max_ms=(?P<max>\d+)"
)


def raiser(exc: BaseException, only: str | None = None):
    def handle(subject_id: str) -> None:
        if only is None or subject_id == only:
            raise exc

    return handle


def round_lines(caplog: pytest.LogCaptureFixture) -> list[re.Match[str]]:
    matches = [
        ROUND.fullmatch(r.getMessage())
        for r in caplog.records
        if r.name == "soc.agent.executor" and r.getMessage().startswith("round ")
    ]
    assert all(matches), [r.getMessage() for r in caplog.records]
    return [m for m in matches if m]


# C6: 한 건을 격리하는 예외


@pytest.mark.parametrize(
    "exc", [SystemExit(SECRET), asyncio.CancelledError(SECRET), RuntimeError(SECRET)]
)
def test_handle_failure_of_any_isolated_kind_keeps_the_stage_running(
    exc: BaseException, caplog: pytest.LogCaptureFixture
) -> None:
    worker = FakeWorker("l1", "a", ["a1", "a2"], on_handle=raiser(exc, only="a1"))
    with caplog.at_level(logging.INFO, logger="soc.agent.executor"):
        executor = start(
            {"l1": {"interval_seconds": 0.01, "workers": ["soc.test:a"]}}, {"a": worker}
        )
        try:
            assert wait_until(lambda: worker.handled == ["a1", "a2"])
            assert wait_until(lambda: len(worker.polls) >= 3)  # 다음 라운드도 돈다
            assert executor.dead_stages() == {}
        finally:
            assert executor.stop() == []
    assert type(exc).__name__ in caplog.text and "a1" in caplog.text
    assert SECRET not in caplog.text


def test_poll_cancelled_error_is_logged_and_the_next_round_polls_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    worker = FakeWorker("l1", "a", ["a1"])
    real_poll = worker.poll
    calls = {"n": 0}

    def poll(limit: int) -> list[str]:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise asyncio.CancelledError(SECRET)
        return real_poll(limit)

    worker.poll = poll  # type: ignore[method-assign]
    with caplog.at_level(logging.INFO, logger="soc.agent.executor"):
        executor = start(
            {"l1": {"interval_seconds": 0.01, "workers": ["soc.test:a"]}}, {"a": worker}
        )
        try:
            assert wait_until(lambda: worker.handled == ["a1"])
            assert executor.dead_stages() == {}
        finally:
            assert executor.stop() == []
    assert caplog.text.count("poll 실패(CancelledError)") >= 2
    assert SECRET not in caplog.text


# C6: 단계 스레드가 죽는 예외


def test_other_base_exception_marks_the_stage_dead_without_traceback(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    hooks: list[Any] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: hooks.append(args))
    dying = FakeWorker("l1", "a", ["a1", "a2"], on_handle=raiser(KeyboardInterrupt(SECRET)))
    other = FakeWorker("l2", "b", ["b1"])
    with caplog.at_level(logging.INFO, logger="soc.agent.executor"):
        executor = start(
            {
                "l1": {"interval_seconds": 0.01, "workers": ["soc.test:a"]},
                "l2": {"interval_seconds": 0.01, "workers": ["soc.test:b"]},
            },
            {"a": dying, "b": other},
        )
        try:
            assert wait_until(lambda: executor.dead_stages() == {"l1": "KeyboardInterrupt"})
            assert wait_until(lambda: other.handled == ["b1"])
            assert dying.handled == ["a1"]  # 죽은 단계는 더 처리하지 않는다
        finally:
            assert executor.stop() == []
    assert hooks == []  # 스레드 밖으로 올리지 않아 메시지가 든 트레이스백이 없다
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert [r.getMessage() for r in errors] == ["l1 단계 스레드가 죽었다(KeyboardInterrupt)"]
    assert errors[0].exc_info is None
    assert SECRET not in caplog.text


def test_dead_stages_is_empty_while_everything_runs() -> None:
    worker = FakeWorker("l1", "a", ["a1"])
    executor = start({"l1": {"interval_seconds": 0.01, "workers": ["soc.test:a"]}}, {"a": worker})
    try:
        assert wait_until(lambda: worker.handled == ["a1"])
        assert executor.dead_stages() == {}
    finally:
        executor.stop()


# C7: 라운드 지표


def test_round_line_has_counts_limit_and_times_and_empty_rounds_are_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    worker = FakeWorker("l1", "a", ["a1", "a2"], on_handle=lambda s: time.sleep(0.05))
    with caplog.at_level(logging.INFO, logger="soc.agent.executor"):
        executor = start(
            {"l1": {"interval_seconds": 0.01, "workers": ["soc.test:a"]}}, {"a": worker}
        )
        try:
            assert wait_until(lambda: worker.handled == ["a1", "a2"])
            assert wait_until(lambda: len(worker.polls) >= 4)  # 빈 라운드가 여러 번 돈다
        finally:
            assert executor.stop() == []
    lines = round_lines(caplog)
    assert len(lines) == 1  # 받은 건이 없는 라운드에는 줄이 없다
    line = lines[0]
    assert (line["stage"], line["worker"]) == ("l1", "a")
    assert (line["polled"], line["limit"], line["handled"], line["failed"]) == ("2", "10", "2", "0")
    assert int(line["total"]) >= int(line["max"]) >= 40
    assert "a1" not in line.group(0)  # subject ID는 넣지 않는다


def test_round_line_marks_saturation_when_polled_reaches_the_limit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    worker = FakeWorker("l1", "a", ["a1", "a2", "a3"])
    with caplog.at_level(logging.INFO, logger="soc.agent.executor"):
        executor = start(
            {"l1": {"interval_seconds": 0.01, "poll_limit": 2, "workers": ["soc.test:a"]}},
            {"a": worker},
        )
        try:
            assert wait_until(lambda: worker.handled == ["a1", "a2", "a3"])
        finally:
            assert executor.stop() == []
    polled = [(m["polled"], m["limit"]) for m in round_lines(caplog)]
    assert polled == [("2", "2"), ("1", "2")]


def test_round_line_counts_failures_without_message_or_subject(
    caplog: pytest.LogCaptureFixture,
) -> None:
    worker = FakeWorker("l1", "a", ["a1", "a2"], on_handle=raiser(RuntimeError(SECRET), only="a1"))
    with caplog.at_level(logging.INFO, logger="soc.agent.executor"):
        executor = start(
            {"l1": {"interval_seconds": 0.01, "workers": ["soc.test:a"]}}, {"a": worker}
        )
        try:
            assert wait_until(lambda: worker.handled == ["a1", "a2"])
            assert wait_until(lambda: len(round_lines(caplog)) == 1)
        finally:
            assert executor.stop() == []
    line = round_lines(caplog)[0]
    assert (line["polled"], line["handled"], line["failed"]) == ("2", "1", "1")
    assert SECRET not in line.group(0)


def test_round_line_is_written_even_when_stop_ends_the_round_early(
    caplog: pytest.LogCaptureFixture,
) -> None:
    release = threading.Event()
    entered = threading.Event()

    def blocking(subject_id: str) -> None:
        entered.set()
        release.wait(WAIT)

    worker = FakeWorker("l1", "a", ["a1", "a2"], on_handle=blocking)
    with caplog.at_level(logging.INFO, logger="soc.agent.executor"):
        executor = start(
            {"l1": {"interval_seconds": 0.01, "workers": ["soc.test:a"]}}, {"a": worker}
        )
        assert entered.wait(WAIT)
        stopper = threading.Thread(target=executor.stop)
        stopper.start()
        time.sleep(0.1)
        release.set()
        stopper.join(WAIT)
    assert worker.handled == ["a1"]  # 종료 요청 뒤 다음 건(a2)은 시작하지 않는다
    line = round_lines(caplog)[0]
    assert (line["polled"], line["handled"], line["failed"]) == ("2", "1", "0")
