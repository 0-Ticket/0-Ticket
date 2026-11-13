"""활성화 파이프 진입점(#316): 준비 점검 실패, 단계 구성, 예외 격리, 빈 반복. DB 없이 본다."""

import logging
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from test_pipeline_check import ENV, OK_PROBES, boom

from soc.pipeline import __main__ as pipeline_main
from soc.pipeline.check import Probes

WAIT = 5.0
FAST = """
[executor.l1]
interval_seconds = 0.05
[executor.l2]
interval_seconds = 0.05
[executor.l3]
interval_seconds = 60
[pipeline]
normalize_interval_seconds = 0.05
ticketing_interval_seconds = 0.05
"""


class Worker:
    def __init__(
        self, stage: str, name: str, items: Sequence[str] = (), *, poll_error: bool = False
    ) -> None:
        self.stage, self.name = stage, name
        self.queue = list(items)
        self.poll_error = poll_error
        self.polls = 0
        self.handled: list[str] = []

    def poll(self, limit: int) -> list[str]:
        self.polls += 1
        if self.poll_error:
            raise RuntimeError("poll 실패(테스트)")
        out, self.queue = self.queue[:limit], self.queue[limit:]
        return out

    def handle(self, subject_id: str) -> None:
        self.handled.append(subject_id)


def make_resolver(workers: dict[str, Worker], built: list[str]) -> Callable[[str], Any]:
    def resolve(path: str) -> Callable[[Any], Worker]:
        built.append(path)
        stage = next(s for s in ("normalize", "ticketing", "l1", "l2", "l3") if s in path)
        return lambda _config: workers.setdefault(path, Worker(stage, path))

    return resolve


def wait_until(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + WAIT
    while not condition():
        assert time.monotonic() < deadline, "기다리는 조건이 되지 않았다"
        time.sleep(0.01)


def run_pipeline(
    config_dir: Path,
    resolve: Callable[[str], Any],
    ready: Callable[[], bool],
    probes: Probes = OK_PROBES,
) -> int:
    stop = threading.Event()
    code: list[int] = []
    thread = threading.Thread(
        target=lambda: code.append(
            pipeline_main.main(
                [],
                config_dir=config_dir,
                stop_event=stop,
                resolve=resolve,
                probes=probes,
                environ=ENV,
            )
        )
    )
    thread.start()
    try:
        wait_until(ready)
    finally:
        stop.set()
        thread.join(WAIT)
    assert not thread.is_alive()
    return code[0]


@pytest.fixture
def config_dir(default_config_dir: Path) -> Path:
    (default_config_dir / "local.toml").write_text(FAST, encoding="utf-8")
    return default_config_dir


def test_failed_check_starts_no_stage_and_exits_4(
    config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built: list[str] = []
    code = pipeline_main.main(
        [],
        config_dir=config_dir,
        resolve=make_resolver({}, built),
        probes=Probes(
            db=boom,
            migrations=OK_PROBES.migrations,
            agent_db=OK_PROBES.agent_db,
            qdrant=OK_PROBES.qdrant,
            embedder=OK_PROBES.embedder,
            llm=OK_PROBES.llm,
        ),
        environ=ENV,
    )
    out = capsys.readouterr()
    assert code == 4
    assert built == []
    assert "FAIL db (RuntimeError)" in out.out
    assert "OK   llm" in out.out  # 하나가 실패해도 나머지 항목은 끝까지 돈다
    assert "준비 완료" not in out.out + out.err
    assert "s3cr3t" not in out.out + out.err


def test_passing_check_runs_four_stages_and_never_l3(
    config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workers: dict[str, Worker] = {}
    built: list[str] = []
    code = run_pipeline(
        config_dir,
        make_resolver(workers, built),
        lambda: len(workers) == 5 and all(w.polls >= 2 for w in workers.values()),
    )
    assert code == 0
    assert sorted(w.stage for w in workers.values()) == ["l1", "l2", "l2", "normalize", "ticketing"]
    assert not [p for p in built if "l3" in p]  # [executor.l3] interval_seconds = 60이어도 안 뜬다
    assert "준비 완료, 수집 명령을 실행하세요" in capsys.readouterr().out


def test_one_stage_failing_does_not_stop_the_others(config_dir: Path) -> None:
    workers = {
        "soc.pipeline.workers:build_normalize_worker": Worker("normalize", "n", poll_error=True),
        "soc.l1.judge:build_worker": Worker("l1", "l1", ["alt_1", "alt_2"]),
    }
    code = run_pipeline(
        config_dir,
        make_resolver(workers, []),
        lambda: (
            workers["soc.l1.judge:build_worker"].handled == ["alt_1", "alt_2"]
            and workers["soc.pipeline.workers:build_normalize_worker"].polls >= 3
        ),
    )
    assert code == 0


def test_idle_rounds_neither_handle_nor_log(
    config_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    workers: dict[str, Worker] = {}
    with caplog.at_level(logging.INFO, logger="soc.agent.executor"):
        run_pipeline(
            config_dir,
            make_resolver(workers, []),
            lambda: len(workers) == 5 and all(w.polls >= 5 for w in workers.values()),
        )
    assert all(w.handled == [] for w in workers.values())
    assert not [r for r in caplog.records if r.getMessage().startswith("round ")]


def test_new_stage_picks_up_items_when_they_appear(config_dir: Path) -> None:
    workers = {"soc.pipeline.workers:build_ticketing_worker": Worker("ticketing", "t")}
    worker = workers["soc.pipeline.workers:build_ticketing_worker"]
    started = time.monotonic()

    def ready() -> bool:
        if worker.polls == 3 and not worker.queue and not worker.handled:
            worker.queue.append("batch")
        return worker.handled == ["batch"]

    run_pipeline(config_dir, make_resolver(workers, []), ready)
    assert time.monotonic() - started < WAIT


def test_entry_point_disables_tracing_without_environment(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_AGENTS_DISABLE_TRACING", raising=False)
    calls: list[bool] = []
    monkeypatch.setattr(pipeline_main, "set_tracing_disabled", calls.append)
    run_pipeline(config_dir, make_resolver({}, []), lambda: bool(calls))
    assert calls[0] is True


def test_bad_pipeline_config_exits_2(config_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (config_dir / "local.toml").write_text("[pipeline]\nnormalize_interval_seconds = 0\n")
    code = pipeline_main.main([], config_dir=config_dir, probes=OK_PROBES, environ=ENV)
    assert code == 2
    assert "normalize_interval_seconds" in capsys.readouterr().err
