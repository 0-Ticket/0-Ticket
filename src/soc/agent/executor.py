"""실행기(#215): 등록한 파이프 워커(AgentWorker)를 단계별 스레드로 돌린다.

- 단계(l1·l2·l3)마다 스레드 하나. 단계 안 동시 실행은 1건이고, 한 라운드에 등록 순서대로 워커마다
  poll(poll_limit) → 받은 ID마다 handle을 한다. 라운드가 끝나면 interval_seconds만큼 쉰다.
- 워커가 없거나 interval_seconds = 0인 단계는 스레드를 띄우지 않는다(poll도 부르지 않는다).
- poll·handle의 Exception·CancelledError·SystemExit은 잡아서 워커 이름·subject ID·예외 종류만
  로그에 남기고 다음 건으로 간다. 예외 메시지는 밖에서 온 문자열일 수 있어 남기지 않는다
  (docs/security.md).
- 그 밖의 BaseException(KeyboardInterrupt 등)이나 스레드 자체의 오류는 종류만 로그에 남기고
  그 단계를 죽은 것으로 표시한다(스레드 밖으로 올리지 않는다). main이 이를 보고 다른 단계를
  정리한 뒤 종료
  코드 3으로 끝낸다. 재시작하지 않는다(D-050).
- 받은 건이 있는 라운드는 워커마다 지표 한 줄(INFO)을 남긴다: round stage=… worker=… polled=…
  limit=… handled=…(성공) failed=… total_ms=…(handle 합) max_ms=…(건당 최대). polled가 limit이면
  밀리고 있다는 신호다. subject ID·예외 메시지는 넣지 않는다.
- 스레드는 asyncio 이벤트 루프를 하나 만들어 그 스레드의 기본 루프로 등록한다. run_agent 안의
  Runner.run_sync는 스레드의 기본 루프를 그대로 쓰므로(openai-agents 0.24.0), 종료할 때 이 루프의
  작업을 취소하면 진행 중인 run이 failure="cancelled"로 끝난다(에이전트 구조, D-024).
- 워커는 [executor.<stage>] workers의 "soc.<모듈>:<함수>"로 등록한다. 함수는 설정 전체를 받아
  워커를 돌려준다(build_worker(config) -> AgentWorker).
"""

import argparse
import asyncio
import importlib
import logging
import re
import signal
import sys
import threading
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents import set_tracing_disabled

from soc.agent.config import load_full_config
from soc.agent.types import STAGES, AgentWorker
from soc.similar.runtime import install_service

logger = logging.getLogger("soc.agent.executor")

# 종료할 때 진행 중인 run에 취소를 다시 보내는 간격(초). 형식 오류 재요청처럼 handle 안에서
# run이 이어지면, 앞 run이 끝난 뒤 새로 시작한 run도 취소해야 하기 때문이다.
CANCEL_INTERVAL = 0.2

# 한 건의 실패로 보고 다음 건으로 가는 예외. 그 밖의 BaseException은 단계를 죽은 것으로 본다(D-050)
_ISOLATED = (Exception, asyncio.CancelledError, SystemExit)

_FACTORY_PATH = re.compile(r"soc(\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*\Z")

Factory = Callable[[dict[str, Any]], Any]
Resolve = Callable[[str], Factory]


class ExecutorConfigError(Exception):
    """[executor] 설정이나 워커 등록이 잘못됐다. 메시지에는 키와 모듈 경로만 담는다."""


@dataclass(frozen=True)
class StageSettings:
    stage: str
    interval_seconds: float
    poll_limit: int
    workers: tuple[str, ...]


def resolve_factory(path: str) -> Factory:
    """ "soc.<모듈>:<함수>"의 함수를 돌려준다. soc. 밖의 모듈은 받지 않는다."""
    if not isinstance(path, str) or not _FACTORY_PATH.match(path):
        raise ExecutorConfigError(f"워커 경로는 'soc.<모듈>:<함수>' 모양이다: {path!r}")
    module_name, attr = path.split(":", 1)
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise ExecutorConfigError(
            f"워커 모듈을 가져오지 못했다({type(exc).__name__}): {module_name}"
        ) from None
    factory = getattr(module, attr, None)
    if factory is None or not callable(factory):
        raise ExecutorConfigError(f"워커 함수가 없다: {path}")
    return factory


def read_settings(config: Mapping[str, Any]) -> tuple[float, list[StageSettings]]:
    """(shutdown_timeout_seconds, 단계별 설정). 빠진 단계는 돌지 않는 단계로 본다."""
    section = config.get("executor")
    if not isinstance(section, Mapping):
        raise ExecutorConfigError("[executor] 설정이 없다")
    unknown = set(section) - {"shutdown_timeout_seconds", *STAGES}
    if unknown:
        raise ExecutorConfigError(f"[executor]에 모르는 키가 있다: {', '.join(sorted(unknown))}")
    timeout = section.get("shutdown_timeout_seconds")
    if not _is_number(timeout) or timeout <= 0:
        raise ExecutorConfigError("[executor] shutdown_timeout_seconds는 0보다 큰 수다")
    stages = []
    for stage in STAGES:
        values = section.get(stage, {"interval_seconds": 0, "poll_limit": 1, "workers": []})
        stages.append(_stage_settings(stage, values))
    return float(timeout), stages


def _stage_settings(stage: str, values: Any) -> StageSettings:
    where = f"[executor.{stage}]"
    if not isinstance(values, Mapping):
        raise ExecutorConfigError(f"{where}은 표다")
    interval = values.get("interval_seconds")
    if not _is_number(interval) or interval < 0:
        raise ExecutorConfigError(f"{where} interval_seconds는 0 이상의 수다")
    limit = values.get("poll_limit")
    if type(limit) is not int or limit < 1:
        raise ExecutorConfigError(f"{where} poll_limit은 1 이상의 정수다")
    workers = values.get("workers")
    if not isinstance(workers, list) or not all(isinstance(w, str) for w in workers):
        raise ExecutorConfigError(f"{where} workers는 문자열 목록이다")
    return StageSettings(stage, float(interval), limit, tuple(workers))


def _is_number(value: Any) -> bool:
    return type(value) in (int, float)


def _build_worker(path: str, stage: str, config: dict[str, Any], resolve: Resolve) -> AgentWorker:
    factory = resolve(path)
    try:
        worker = factory(config)
    except Exception as exc:
        raise ExecutorConfigError(f"{path}가 워커를 만들지 못했다({type(exc).__name__})") from None
    name = getattr(worker, "name", None)
    if not isinstance(name, str) or not name:
        raise ExecutorConfigError(f"{path}의 워커에 name이 없다")
    if not callable(getattr(worker, "poll", None)) or not callable(getattr(worker, "handle", None)):
        raise ExecutorConfigError(f"{path}의 워커에 poll·handle이 없다")
    if getattr(worker, "stage", None) != stage:
        raise ExecutorConfigError(f"{path}의 워커 stage가 [executor.{stage}]와 다르다")
    return worker


def _cancel_all(loop: asyncio.AbstractEventLoop) -> None:
    for task in asyncio.all_tasks(loop):
        task.cancel()


class _StageThread:
    def __init__(
        self, settings: StageSettings, workers: Sequence[AgentWorker], stop: threading.Event
    ) -> None:
        self.stage = settings.stage
        self._settings = settings
        self._workers = list(workers)
        self._stop = stop
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self.died: str | None = None  # 스레드를 끝낸 예외 종류
        self.thread = threading.Thread(
            target=self._run, name=f"soc-agent-{self.stage}", daemon=True
        )

    def cancel_running(self) -> None:
        """그 스레드 루프의 작업을 모두 취소하게 한다. 루프가 쉬는 중이면 다음 run에서 취소된다."""
        with self._lock:
            if self._loop is not None:
                self._loop.call_soon_threadsafe(_cancel_all, self._loop)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
        try:
            while not self._stop.is_set():
                self._round()
                self._stop.wait(self._settings.interval_seconds)
        except BaseException as exc:  # 다시 올리지 않는다. 메시지가 든 트레이스백이 stderr에 찍힌다
            self.died = type(exc).__name__
            logger.error("%s 단계 스레드가 죽었다(%s)", self.stage, self.died)
        finally:
            with self._lock:
                self._loop = None  # 닫힌 루프에 취소를 보내지 않게 닫기 전에 비운다
            asyncio.set_event_loop(None)
            loop.close()

    def _round(self) -> None:
        for worker in self._workers:
            if self._stop.is_set():
                return
            try:
                subject_ids = list(worker.poll(self._settings.poll_limit))
            except _ISOLATED as exc:
                logger.warning("%s %s poll 실패(%s)", self.stage, worker.name, type(exc).__name__)
                continue
            if subject_ids:
                self._handle_all(worker, subject_ids)

    def _handle_all(self, worker: AgentWorker, subject_ids: list[str]) -> None:
        handled = failed = 0
        total = longest = 0.0
        try:
            for subject_id in subject_ids:
                if self._stop.is_set():
                    return
                started = time.perf_counter()
                try:
                    worker.handle(subject_id)
                    handled += 1
                except _ISOLATED as exc:
                    failed += 1
                    logger.warning(
                        "%s %s handle 실패 subject=%r (%s)",
                        self.stage,
                        worker.name,
                        subject_id,
                        type(exc).__name__,
                    )
                finally:
                    took = time.perf_counter() - started
                    total += took
                    longest = max(longest, took)
        finally:  # 종료로 일찍 끝나거나 단계가 죽어도 그때까지의 값을 남긴다
            logger.info(
                "round stage=%s worker=%s polled=%d limit=%d handled=%d failed=%d"
                " total_ms=%d max_ms=%d",
                self.stage,
                worker.name,
                len(subject_ids),
                self._settings.poll_limit,
                handled,
                failed,
                total * 1000,
                longest * 1000,
            )


class Executor:
    """설정으로 워커를 만들고 단계별 스레드로 돌린다. 잘못된 설정은 만들 때 ExecutorConfigError."""

    def __init__(self, config: dict[str, Any], *, resolve: Resolve = resolve_factory) -> None:
        self.shutdown_timeout_seconds, settings = read_settings(config)
        self._stop = threading.Event()
        self._threads: list[_StageThread] = []
        for stage in settings:
            if stage.interval_seconds == 0 or not stage.workers:
                continue  # 돌지 않는 단계는 워커도 만들지 않는다
            workers = [_build_worker(p, stage.stage, config, resolve) for p in stage.workers]
            names = [w.name for w in workers]
            if len(set(names)) != len(names):
                raise ExecutorConfigError(f"[executor.{stage.stage}]에 같은 name의 워커가 있다")
            self._threads.append(_StageThread(stage, workers, self._stop))

    @property
    def stages(self) -> list[str]:
        """스레드를 띄우는 단계."""
        return [t.stage for t in self._threads]

    def dead_stages(self) -> dict[str, str]:
        """예외로 스레드가 끝난 단계와 그 예외 종류(D-050)."""
        return {t.stage: t.died for t in self._threads if t.died is not None}

    def start(self) -> None:
        for t in self._threads:
            t.thread.start()

    def stop(self, timeout: float | None = None) -> list[str]:
        """새 건을 시작하지 않고, 진행 중인 run을 취소하며 기다린다. 시간 안에 못 끝난 단계 목록."""
        self._stop.set()
        limit = self.shutdown_timeout_seconds if timeout is None else timeout
        deadline = time.monotonic() + limit
        while True:
            alive = [t for t in self._threads if t.thread.is_alive()]
            remaining = deadline - time.monotonic()
            if not alive or remaining <= 0:
                break
            for t in alive:
                t.cancel_running()
            for t in alive:
                t.thread.join(min(CANCEL_INTERVAL, max(remaining, 0)))
        unfinished = [t.stage for t in self._threads if t.thread.is_alive()]
        if unfinished:
            logger.warning("종료 대기 시간 안에 끝나지 않은 단계: %s", ", ".join(unfinished))
        return unfinished


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="python -m soc.agent",
        description=(
            "등록한 파이프 워커를 단계별 스레드로 돌린다([executor] 설정). Ctrl+C·SIGTERM으로"
            " 끝내면 진행 중인 run을 cancelled로 끝낸다"
        ),
    )


def main(
    argv: list[str] | None = None,
    *,
    config_dir: Path | None = None,
    stop_event: threading.Event | None = None,
    resolve: Resolve = resolve_factory,
) -> int:
    """uv run python -m soc.agent. 종료 코드: 0 정상, 1 종료 대기 시간 초과, 2 설정 오류,
    3 단계 스레드가 죽음(D-050)."""
    build_parser().parse_args(argv)
    set_tracing_disabled(True)  # 진입점에서 끈다(D-022). run_agent도 다시 끈다
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    def err(line: str) -> None:
        print(line, file=sys.stderr)

    try:
        config = load_full_config(config_dir)
        install_service(config)  # 워커가 만들어지기 전에: L1 워커가 색인 함수를 받아 간다(#313)
        executor = Executor(config, resolve=resolve)
    except ExecutorConfigError as exc:
        err(f"실행기 설정 오류: {exc}")
        return 2
    except (OSError, tomllib.TOMLDecodeError) as exc:
        err(f"설정 파일을 읽지 못했다({type(exc).__name__})")
        return 2
    if not executor.stages:
        err("등록된 워커가 없다. [executor.<단계>]의 workers와 interval_seconds를 확인한다")
        return 0
    stop = threading.Event() if stop_event is None else stop_event
    if stop_event is None and threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: stop.set())
    executor.start()
    err(f"실행 중: {', '.join(executor.stages)}. 끝내려면 Ctrl+C")
    while not stop.wait(0.5):
        if executor.dead_stages():
            break
    dead = executor.dead_stages()
    if dead:
        err("단계 스레드가 죽었다: " + ", ".join(f"{s}({name})" for s, name in dead.items()))
    err("종료 중: 진행 중인 run을 취소한다")
    unfinished = executor.stop()
    if executor.dead_stages():
        return 3
    return 1 if unfinished else 0
