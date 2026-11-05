"""실행기(#215): 단계별 스레드, 단계 안 순차, 예외 격리, interval 0, 종료 시 cancelled.

DB 없이 본다.

워커는 테스트 안의 가짜 워커다. 등록 모듈은 soc. 아래만 받으므로, 테스트는 resolve 인자로
"soc.test:<이름>" 경로를 가짜 build_worker에 잇는다.
"""

import asyncio
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from agents.models.interface import Model
from test_agent_core import CONFIG, REGISTRY, make_task

from soc.agent import AgentWorker
from soc.agent.agent_log import MemoryLogSink
from soc.agent.config import load_full_config
from soc.agent.executor import Executor, ExecutorConfigError, main, resolve_factory
from soc.agent.runner import run_task

WAIT = 5.0  # 테스트가 기다리는 최대 초. 정상이면 훨씬 빨리 끝난다


class FakeWorker:
    """items를 한 번씩 내놓는다. handle은 on_handle(subject_id)을 부른다."""

    def __init__(
        self,
        stage: str,
        name: str,
        items: Sequence[str] = (),
        *,
        on_handle: Callable[[str], None] | None = None,
        poll_error: bool = False,
    ) -> None:
        self.stage = stage
        self.name = name
        self.queue = list(items)
        self.on_handle = on_handle
        self.poll_error = poll_error
        self.polls: list[int] = []
        self.handled: list[str] = []

    def poll(self, limit: int) -> list[str]:
        self.polls.append(limit)
        if self.poll_error:
            raise RuntimeError("poll 실패(테스트)")
        out, self.queue = self.queue[:limit], self.queue[limit:]
        return out

    def handle(self, subject_id: str) -> None:
        self.handled.append(subject_id)
        if self.on_handle is not None:
            self.on_handle(subject_id)


def executor_config(
    stages: dict[str, dict[str, Any]], *, shutdown_timeout_seconds: float = 5
) -> dict[str, Any]:
    section: dict[str, Any] = {"shutdown_timeout_seconds": shutdown_timeout_seconds}
    for stage in ("l1", "l2", "l3"):
        section[stage] = {"interval_seconds": 0, "poll_limit": 10, "workers": []}
        section[stage].update(stages.get(stage, {}))
    return {"executor": section}


def resolver(workers: dict[str, Any]) -> Callable[[str], Callable[[dict[str, Any]], Any]]:
    """ "soc.test:<이름>" → workers[이름]을 돌려주는 build_worker."""

    def resolve(path: str) -> Callable[[dict[str, Any]], Any]:
        name = path.split(":", 1)[1]
        return lambda config: workers[name]

    return resolve


def start(stages: dict[str, dict[str, Any]], workers: dict[str, Any], **kwargs: Any) -> Executor:
    executor = Executor(executor_config(stages, **kwargs), resolve=resolver(workers))
    executor.start()
    return executor


def wait_until(condition: Callable[[], bool], timeout: float = WAIT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def test_fake_worker_matches_protocol() -> None:
    worker: AgentWorker = FakeWorker("l1", "fake")  # 타입 검사용
    assert worker.stage == "l1"


def test_stages_run_in_parallel() -> None:
    """l1의 handle은 l2의 handle이 시작해야 끝난다. 둘이 동시에 돌지 않으면 시간 안에 못 끝난다."""
    l1_started, l2_started = threading.Event(), threading.Event()
    met: list[str] = []

    def l1_handle(subject_id: str) -> None:
        l1_started.set()
        if l2_started.wait(WAIT):
            met.append("l1")

    def l2_handle(subject_id: str) -> None:
        l2_started.set()
        if l1_started.wait(WAIT):
            met.append("l2")

    workers = {
        "a": FakeWorker("l1", "a", ["alt_1"], on_handle=l1_handle),
        "b": FakeWorker("l2", "b", ["tkt_1"], on_handle=l2_handle),
    }
    executor = start(
        {
            "l1": {"interval_seconds": 0.01, "workers": ["soc.test:a"]},
            "l2": {"interval_seconds": 0.01, "workers": ["soc.test:b"]},
        },
        workers,
    )
    try:
        assert wait_until(lambda: len(met) == 2)
    finally:
        assert executor.stop() == []
    assert sorted(met) == ["l1", "l2"]


def test_workers_in_one_stage_run_one_at_a_time_in_turn() -> None:
    active = 0
    peak = 0
    order: list[str] = []
    lock = threading.Lock()

    def track(subject_id: str) -> None:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            order.append(subject_id)
        time.sleep(0.02)
        with lock:
            active -= 1

    workers = {
        "a": FakeWorker("l1", "a", ["a1", "a2", "a3"], on_handle=track),
        "b": FakeWorker("l1", "b", ["b1", "b2", "b3"], on_handle=track),
    }
    executor = start(
        {
            "l1": {
                "interval_seconds": 0.01,
                "poll_limit": 2,
                "workers": ["soc.test:a", "soc.test:b"],
            }
        },
        workers,
    )
    try:
        assert wait_until(lambda: len(order) == 6)
    finally:
        assert executor.stop() == []
    assert peak == 1
    # 라운드마다 등록 순서대로 워커가 poll_limit개씩 처리한다
    assert order == ["a1", "a2", "b1", "b2", "a3", "b3"]
    assert workers["a"].polls[0] == 2


def test_exception_in_one_worker_does_not_stop_others(caplog: pytest.LogCaptureFixture) -> None:
    def boom(subject_id: str) -> None:
        if subject_id == "a1":
            raise RuntimeError("공격자가 쓴 문장일 수 있는 메시지")

    workers = {
        "a": FakeWorker("l1", "a", ["a1", "a2"], on_handle=boom),
        "b": FakeWorker("l1", "b", ["b1"]),
        "c": FakeWorker("l1", "c", poll_error=True),
        "d": FakeWorker("l2", "d", ["d1"]),
    }
    executor = start(
        {
            "l1": {
                "interval_seconds": 0.01,
                "workers": ["soc.test:a", "soc.test:b", "soc.test:c"],
            },
            "l2": {"interval_seconds": 0.01, "workers": ["soc.test:d"]},
        },
        workers,
    )
    try:
        assert wait_until(
            lambda: (
                workers["a"].handled == ["a1", "a2"]
                and workers["b"].handled == ["b1"]
                and workers["d"].handled == ["d1"]
                and len(workers["c"].polls) >= 2
            )
        )
    finally:
        assert executor.stop() == []
    # 로그에는 워커 이름·subject ID·예외 종류만 남고 메시지는 남지 않는다
    text = caplog.text
    assert "RuntimeError" in text and "a1" in text
    assert "공격자" not in text and "poll 실패(테스트)" not in text


def test_stage_with_interval_zero_is_not_polled() -> None:
    workers = {
        "a": FakeWorker("l1", "a", ["a1"]),
        "z": FakeWorker("l3", "z", ["hnt_1"]),
    }
    executor = start(
        {
            "l1": {"interval_seconds": 0.01, "workers": ["soc.test:a"]},
            "l3": {"interval_seconds": 0, "workers": ["soc.test:z"]},
        },
        workers,
    )
    try:
        assert wait_until(lambda: workers["a"].handled == ["a1"])
        time.sleep(0.05)
    finally:
        assert executor.stop() == []
    assert executor.stages == ["l1"]
    assert workers["z"].polls == []


def test_stage_without_workers_starts_no_thread() -> None:
    executor = Executor(executor_config({"l1": {"interval_seconds": 10}}), resolve=resolver({}))
    assert executor.stages == []


class SlowModel(Model):
    """모델 호출이 끝나지 않는다. 취소돼야만 돌아온다."""

    def __init__(self) -> None:
        self.called = threading.Event()

    async def get_response(self, *args: Any, **kwargs: Any) -> Any:
        self.called.set()
        await asyncio.sleep(60)

    def stream_response(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


def test_stop_cancels_running_run_agent() -> None:
    model = SlowModel()
    sink = MemoryLogSink()
    results: list[Any] = []

    def run_one(subject_id: str) -> None:
        results.append(
            run_task(
                make_task(),
                model=model,
                model_name="slow",
                log_sink=sink,
                config=CONFIG,
                registry=REGISTRY,
            )
        )

    workers = {"a": FakeWorker("l1", "a", ["a1", "a2"], on_handle=run_one)}
    executor = start({"l1": {"interval_seconds": 0.01, "workers": ["soc.test:a"]}}, workers)
    assert model.called.wait(WAIT)
    started = time.monotonic()
    assert executor.stop() == []
    assert time.monotonic() - started < 2
    assert [r.failure for r in results] == ["cancelled"]  # 종료 뒤 다음 건(a2)은 시작하지 않는다
    assert workers["a"].handled == ["a1"]
    assert [(r["kind"], r["outcome"], r["details"]["failure"]) for r in sink.rows] == [
        ("model", "error", "cancelled")
    ]


def test_stop_cancels_a_run_that_starts_after_the_stop_request() -> None:
    """형식 오류 재요청처럼 handle 안에서 run이 이어질 때도 다음 run까지 취소한다."""
    model = SlowModel()
    results: list[Any] = []
    gate = threading.Event()

    def later_run(subject_id: str) -> None:
        gate.set()
        time.sleep(0.3)  # 이 사이에 종료 요청이 온다(루프에는 아직 작업이 없다)
        results.append(
            run_task(
                make_task(),
                model=model,
                model_name="slow",
                log_sink=MemoryLogSink(),
                config=CONFIG,
                registry=REGISTRY,
            )
        )

    workers = {"a": FakeWorker("l1", "a", ["a1"], on_handle=later_run)}
    executor = start({"l1": {"interval_seconds": 0.01, "workers": ["soc.test:a"]}}, workers)
    assert gate.wait(WAIT)
    assert executor.stop() == []
    assert [r.failure for r in results] == ["cancelled"]


def test_stop_reports_stage_that_did_not_finish_in_time() -> None:
    release = threading.Event()

    def blocking(subject_id: str) -> None:
        release.wait(WAIT)  # 이벤트 루프 밖에서 막혀 취소가 닿지 않는다

    workers = {"a": FakeWorker("l1", "a", ["a1"], on_handle=blocking)}
    executor = start(
        {"l1": {"interval_seconds": 0.01, "workers": ["soc.test:a"]}},
        workers,
        shutdown_timeout_seconds=0.3,
    )
    try:
        assert wait_until(lambda: workers["a"].handled == ["a1"])
        assert executor.stop() == ["l1"]
    finally:
        release.set()


@pytest.mark.parametrize(
    "path",
    [
        "tests.fake:build_worker",  # soc. 밖
        "soc.agent.runner",  # 함수 이름 없음
        "soc..agent:build_worker",
        "soc.agent:build-worker",
        "os:system",
    ],
)
def test_resolve_rejects_paths_outside_soc_or_malformed(path: str) -> None:
    with pytest.raises(ExecutorConfigError):
        resolve_factory(path)


def test_resolve_rejects_missing_module_or_function() -> None:
    with pytest.raises(ExecutorConfigError):
        resolve_factory("soc.no_such_module:build_worker")
    with pytest.raises(ExecutorConfigError):
        resolve_factory("soc.agent.runner:no_such_function")
    with pytest.raises(ExecutorConfigError):
        resolve_factory("soc.agent.config:SECTIONS")  # 함수가 아니다


def test_resolve_returns_function() -> None:
    from soc.agent.runner import run_agent

    assert resolve_factory("soc.agent.runner:run_agent") is run_agent


def test_factory_gets_whole_config() -> None:
    seen: list[dict[str, Any]] = []
    worker = FakeWorker("l1", "a")

    def resolve(path: str) -> Callable[[dict[str, Any]], Any]:
        def build(config: dict[str, Any]) -> Any:
            seen.append(config)
            return worker

        return build

    config = executor_config({"l1": {"interval_seconds": 1, "workers": ["soc.test:a"]}})
    config["l1"] = {"own": True}
    Executor(config, resolve=resolve)
    assert seen == [config]


@pytest.mark.parametrize(
    ("stages", "workers"),
    [
        # 등록한 단계와 워커의 stage가 다르다
        ({"l1": {"interval_seconds": 1, "workers": ["soc.test:a"]}}, {"a": FakeWorker("l2", "a")}),
        # 같은 단계에 name이 겹친다
        (
            {"l1": {"interval_seconds": 1, "workers": ["soc.test:a", "soc.test:b"]}},
            {"a": FakeWorker("l1", "same"), "b": FakeWorker("l1", "same")},
        ),
        # 워커 모양이 아니다
        ({"l1": {"interval_seconds": 1, "workers": ["soc.test:a"]}}, {"a": object()}),
        ({"l1": {"interval_seconds": 1, "workers": ["soc.test:a"]}}, {"a": FakeWorker("l1", "")}),
    ],
)
def test_bad_workers_are_rejected_at_start(
    stages: dict[str, dict[str, Any]], workers: dict[str, Any]
) -> None:
    with pytest.raises(ExecutorConfigError):
        Executor(executor_config(stages), resolve=resolver(workers))


def test_factory_exception_is_config_error() -> None:
    def resolve(path: str) -> Callable[[dict[str, Any]], Any]:
        def build(config: dict[str, Any]) -> Any:
            raise RuntimeError("설정 없음")

        return build

    config = executor_config({"l1": {"interval_seconds": 1, "workers": ["soc.test:a"]}})
    with pytest.raises(ExecutorConfigError):
        Executor(config, resolve=resolve)


@pytest.mark.parametrize(
    "change",
    [
        {"interval_seconds": -1},
        {"interval_seconds": "10"},
        {"interval_seconds": True},
        {"poll_limit": 0},
        {"poll_limit": 1.5},
        {"workers": "soc.test:a"},
        {"workers": [1]},
    ],
)
def test_bad_stage_settings_are_rejected(change: dict[str, Any]) -> None:
    with pytest.raises(ExecutorConfigError):
        Executor(executor_config({"l1": change}), resolve=resolver({}))


def test_bad_executor_section_is_rejected() -> None:
    with pytest.raises(ExecutorConfigError):
        Executor({}, resolve=resolver({}))  # [executor] 없음
    config = executor_config({})
    config["executor"]["l4"] = {"interval_seconds": 1, "poll_limit": 1, "workers": []}
    with pytest.raises(ExecutorConfigError):
        Executor(config, resolve=resolver({}))
    config = executor_config({}, shutdown_timeout_seconds=0)
    with pytest.raises(ExecutorConfigError):
        Executor(config, resolve=resolver({}))


def test_default_config_executor_values(default_config_dir: Path) -> None:
    section = load_full_config(default_config_dir)["executor"]
    assert section["shutdown_timeout_seconds"] == 30
    assert [section[s]["interval_seconds"] for s in ("l1", "l2", "l3")] == [10, 10, 0]
    assert [section[s]["poll_limit"] for s in ("l1", "l2", "l3")] == [10, 10, 10]
    assert [section[s]["workers"] for s in ("l1", "l2", "l3")] == [[], [], []]
    # 기본 설정에는 워커가 없어 띄울 단계가 없다
    assert Executor(load_full_config(default_config_dir)).stages == []


def test_main_without_workers_exits_zero(
    default_config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([], config_dir=default_config_dir) == 0
    assert "등록된 워커가 없다" in capsys.readouterr().err


def test_main_runs_until_stop_event(tmp_path: Path) -> None:
    (tmp_path / "default.toml").write_text(
        "[executor]\nshutdown_timeout_seconds = 5\n"
        "[executor.l1]\ninterval_seconds = 0.01\npoll_limit = 1\nworkers = ['soc.test:a']\n"
        "[executor.l2]\ninterval_seconds = 0\npoll_limit = 1\nworkers = []\n"
        "[executor.l3]\ninterval_seconds = 0\npoll_limit = 1\nworkers = []\n",
        encoding="utf-8",
    )
    worker = FakeWorker("l1", "a", ["a1"])
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    code = main([], config_dir=tmp_path, stop_event=stop, resolve=resolver({"a": worker}))
    assert code == 0
    assert worker.handled == ["a1"]


def test_main_with_bad_config_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "default.toml").write_text(
        "[executor]\nshutdown_timeout_seconds = 5\n"
        "[executor.l1]\ninterval_seconds = 1\npoll_limit = 1\nworkers = ['tests.x:build']\n"
        "[executor.l2]\ninterval_seconds = 0\npoll_limit = 1\nworkers = []\n"
        "[executor.l3]\ninterval_seconds = 0\npoll_limit = 1\nworkers = []\n",
        encoding="utf-8",
    )
    assert main([], config_dir=tmp_path) == 2
    assert "설정" in capsys.readouterr().err
