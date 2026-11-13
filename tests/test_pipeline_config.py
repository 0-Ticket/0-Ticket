"""활성화 파이프 설정(#316): [pipeline] 읽기와 파이프용 [executor] 설정 만들기.

DB 없이 본다. 기존 `python -m soc.agent`의 기본 설정이 바뀌지 않는 것도 여기서 고정한다.
"""

from pathlib import Path
from typing import Any

import pytest

from soc.agent.config import load_full_config
from soc.agent.executor import Executor, ExecutorConfigError
from soc.pipeline.config import PipelineConfigError, build_executor_config, read_pipeline

NORMALIZE_WORKER = "soc.pipeline.workers:build_normalize_worker"
TICKETING_WORKER = "soc.pipeline.workers:build_ticketing_worker"


class Fake:
    def __init__(self, stage: str, name: str) -> None:
        self.stage, self.name = stage, name

    def poll(self, limit: int) -> list[str]:
        return []

    def handle(self, subject_id: str) -> None:
        pass


def resolve(path: str) -> Any:
    if "l3" in path:
        raise AssertionError("L3 워커를 만들면 안 된다")
    stage = next((s for s in ("normalize", "ticketing", "l1") if s in path), "l2")
    return lambda _config: Fake(stage, path)


def test_default_pipeline_section(default_config_dir: Path) -> None:
    settings = read_pipeline(load_full_config(default_config_dir))
    assert settings.normalize_interval_seconds == 3
    assert settings.ticketing_interval_seconds == 3
    assert settings.shutdown_timeout_seconds == 30


def test_executor_config_adds_two_stages_and_forces_l3_off(default_config_dir: Path) -> None:
    (default_config_dir / "local.toml").write_text(
        "[executor.l3]\ninterval_seconds = 60\n[pipeline]\nshutdown_timeout_seconds = 7\n",
        encoding="utf-8",
    )
    config = load_full_config(default_config_dir)
    section = build_executor_config(config)["executor"]
    assert section["normalize"] == {
        "interval_seconds": 3,
        "poll_limit": 1,
        "workers": [NORMALIZE_WORKER],
    }
    assert section["ticketing"] == {
        "interval_seconds": 3,
        "poll_limit": 1,
        "workers": [TICKETING_WORKER],
    }
    assert section["l3"]["interval_seconds"] == 0
    assert section["shutdown_timeout_seconds"] == 7
    assert section["l1"] == config["executor"]["l1"]
    # 입력 설정은 바꾸지 않는다
    assert config["executor"]["l3"]["interval_seconds"] == 60
    assert "normalize" not in config["executor"]


def test_pipeline_executor_runs_four_stages_and_never_l3(default_config_dir: Path) -> None:
    (default_config_dir / "local.toml").write_text(
        "[executor.l3]\ninterval_seconds = 60\n", encoding="utf-8"
    )
    config = build_executor_config(load_full_config(default_config_dir))
    assert Executor(config, resolve=resolve).stages == ["normalize", "ticketing", "l1", "l2"]


def test_default_executor_config_has_no_pipeline_stages(default_config_dir: Path) -> None:
    config = load_full_config(default_config_dir)
    assert set(config["executor"]) == {"shutdown_timeout_seconds", "l1", "l2", "l3"}
    assert Executor(config, resolve=resolve).stages == ["l1", "l2"]


def test_executor_still_rejects_unknown_stage(default_config_dir: Path) -> None:
    config = load_full_config(default_config_dir)
    config["executor"]["l4"] = {"interval_seconds": 1, "poll_limit": 1, "workers": []}
    with pytest.raises(ExecutorConfigError, match="l4"):
        Executor(config, resolve=resolve)


@pytest.mark.parametrize("key", ["normalize_interval_seconds", "ticketing_interval_seconds"])
@pytest.mark.parametrize("value", [0, -1, "3", True])
def test_bad_interval_is_rejected(default_config_dir: Path, key: str, value: Any) -> None:
    config = load_full_config(default_config_dir)
    config["pipeline"][key] = value
    with pytest.raises(PipelineConfigError, match=key):
        read_pipeline(config)


@pytest.mark.parametrize("value", [0, -5, "30"])
def test_bad_shutdown_timeout_is_rejected(default_config_dir: Path, value: Any) -> None:
    config = load_full_config(default_config_dir)
    config["pipeline"]["shutdown_timeout_seconds"] = value
    with pytest.raises(PipelineConfigError, match="shutdown_timeout_seconds"):
        read_pipeline(config)


def test_missing_pipeline_section_is_rejected(default_config_dir: Path) -> None:
    config = load_full_config(default_config_dir)
    del config["pipeline"]
    with pytest.raises(PipelineConfigError, match="pipeline"):
        read_pipeline(config)
