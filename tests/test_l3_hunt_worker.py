"""L3 헌팅 실행기 워커의 등록(#245). DB 없이 본다(build_worker는 DB에 접속하지 않는다)."""

import copy
from pathlib import Path
from typing import Any

import pytest

from soc.agent.config import load_full_config
from soc.agent.executor import Executor, ExecutorConfigError, resolve_factory
from soc.l3.hunt.generate import HuntGenerator
from soc.l3.hunt.generate import build_worker as build_generator
from soc.l3.hunt.settings import ConfigError
from soc.l3.hunt.verify import HuntVerifier
from soc.l3.hunt.verify import build_worker as build_verifier
from soc.l3.intel import collect as intel

WORKERS = ["soc.l3.hunt.generate:build_worker", "soc.l3.hunt.verify:build_worker"]
FAKE_URL = "postgresql://nobody@127.0.0.1:1/none"  # 접속하지 않는다


@pytest.fixture
def config(default_config_dir: Path) -> dict[str, Any]:
    return load_full_config(default_config_dir)


def l3_only(config: dict[str, Any]) -> dict[str, Any]:
    """L1·L2 단계를 끈 설정. 기본 설정은 L1·L2 워커가 켜져 있어, 실제 등록 경로로 Executor를
    만들면 그 워커(필요한 설정·Qdrant)까지 만든다. 여기서는 L3 등록만 본다."""
    out = copy.deepcopy(config)
    for stage in ("l1", "l2"):
        out["executor"][stage]["interval_seconds"] = 0
    return out


def with_hunt(config: dict[str, Any], **hunt: Any) -> dict[str, Any]:
    out = copy.deepcopy(config)
    out["l3"]["hunt"].update(hunt)
    return out


def test_default_config_registers_both_l3_workers_but_keeps_l3_off(
    config: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    section = config["executor"]["l3"]

    assert section["workers"] == WORKERS  # 생성이 먼저라 같은 라운드에서 검증된다
    assert section["interval_seconds"] == 0
    # interval 0이면 워커를 만들지 않으므로 DATABASE_URL이 없어도 실행기가 L3를 띄우지 않는다
    assert Executor(l3_only(config)).stages == []
    assert config["l3"]["hunt"]["generate_interval_seconds"] == 86_400


def test_turning_l3_on_builds_both_workers_in_order(
    config: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    config = l3_only(config)
    config["executor"]["l3"]["interval_seconds"] = 600
    built: list[Any] = []

    def resolve(path: str) -> Any:
        factory = resolve_factory(path)

        def recording(cfg: dict[str, Any]) -> Any:
            worker = factory(cfg)
            built.append(worker)
            return worker

        return recording

    executor = Executor(config, resolve=resolve)

    assert executor.stages == ["l3"]
    assert [type(w) for w in built] == [HuntGenerator, HuntVerifier]
    assert [(w.stage, w.name) for w in built] == [
        ("l3", "l3_hunt_hypothesize"),
        ("l3", "l3_hunt_verify"),
    ]


def test_turning_l3_on_without_database_url_refuses_to_start(
    config: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    config = l3_only(config)
    config["executor"]["l3"]["interval_seconds"] = 600

    # 등록 순서상 생성 워커가 먼저 만들어지다 실패한다
    with pytest.raises(ExecutorConfigError, match=r"soc\.l3\.hunt\.generate.*만들지 못했다"):
        Executor(config)


@pytest.mark.parametrize("build", [build_generator, build_verifier])
def test_build_worker_needs_database_url(
    build: Any, config: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ConfigError, match="DATABASE_URL"):
        build(config)


@pytest.mark.parametrize("build", [build_generator, build_verifier])
def test_build_worker_rejects_broken_hunt_settings(
    build: Any, config: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)

    with pytest.raises(ConfigError):
        build(with_hunt(config, max_attempts=0))


@pytest.mark.parametrize("value", [0, -1, "86400", True, None])
def test_generator_rejects_broken_interval(
    value: Any, config: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    broken = with_hunt(config)
    if value is None:
        del broken["l3"]["hunt"]["generate_interval_seconds"]
    else:
        broken["l3"]["hunt"]["generate_interval_seconds"] = value

    with pytest.raises(ConfigError, match="generate_interval_seconds"):
        build_generator(broken)


def test_generator_reads_intel_settings_only_when_collecting(
    config: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    no_collect = with_hunt(config, collect_before=False)
    del no_collect["l3"]["intel"]["sources"]  # 수집하지 않으면 출처 설정이 틀려도 된다

    assert isinstance(build_generator(no_collect), HuntGenerator)
    with pytest.raises(intel.ConfigError, match="sources"):
        build_generator(with_hunt(no_collect, collect_before=True))


def test_manual_hunt_settings_do_not_need_the_interval(config: dict[str, Any]) -> None:
    """generate_interval_seconds는 생성 워커만 읽는다. 수동 명령(soc.l3 hunt)의 설정은 그대로다."""
    from soc.l3.hunt.settings import read_hunt_settings

    l3 = copy.deepcopy(config["l3"])
    del l3["hunt"]["generate_interval_seconds"]

    assert read_hunt_settings(l3).max_attempts == 2
