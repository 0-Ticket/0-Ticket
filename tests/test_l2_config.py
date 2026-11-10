"""L2 설정 로더와 분류 설정 검증."""

import copy
from pathlib import Path

import pytest

from soc.l2.config import ConfigError, load_config, read_analyze_settings, read_settings

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"


def test_default_config_reads_into_branch_settings() -> None:
    config = load_config(REPO_CONFIG)
    settings = read_settings(config["l2"])

    assert set(config) == {"l2"}
    assert settings.candidate_window_ms == 86_400_000
    assert settings.max_candidates == 5
    assert settings.candidate_source == "vector"
    assert settings.top_k == 50


def test_default_config_reads_into_analyze_settings() -> None:
    settings = read_analyze_settings(load_config(REPO_CONFIG)["l2"])

    assert settings.lookback_ms == 86_400_000
    assert settings.max_failures == 3
    assert settings.failure_retry_cooldown_ms == 3_600_000
    assert settings.max_seed_entities == 10
    assert settings.max_related_per_entity == 20


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c.pop("analyze"),
        lambda c: c["analyze"].update(lookback_ms=0),
        lambda c: c["analyze"].update(max_failures=True),
        lambda c: c["analyze"].update(failure_retry_cooldown_ms=0),
        lambda c: c["analyze"].update(max_seed_entities="10"),
        lambda c: c["analyze"].update(max_related_per_entity=0),
        lambda c: c["analyze"].update(extra=1),
    ],
)
def test_bad_analyze_settings_are_rejected(change) -> None:
    l2 = copy.deepcopy(load_config(REPO_CONFIG)["l2"])
    change(l2)

    with pytest.raises(ConfigError):
        read_analyze_settings(l2)


def test_local_overrides_default_and_only_l2_is_returned(tmp_path: Path) -> None:
    (tmp_path / "default.toml").write_text(
        "[l2.branch]\n"
        "candidate_window_ms = 1000\n"
        "max_candidates = 5\n"
        'candidate_source = "vector"\n'
        "top_k = 50\n"
        "[other]\nx = 1\n",
        encoding="utf-8",
    )
    (tmp_path / "local.toml").write_text(
        "[l2.branch]\nmax_candidates = 2\n[other]\nx = 2\n", encoding="utf-8"
    )

    config = load_config(tmp_path)

    assert config == {
        "l2": {
            "branch": {
                "candidate_window_ms": 1000,
                "max_candidates": 2,
                "candidate_source": "vector",
                "top_k": 50,
            }
        }
    }


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c.pop("branch"),
        lambda c: c["branch"].update(candidate_window_ms=0),
        lambda c: c["branch"].update(candidate_window_ms=True),
        lambda c: c["branch"].update(max_candidates=0),
        lambda c: c["branch"].update(max_candidates="5"),
        lambda c: c["branch"].update(candidate_source="direct"),
        lambda c: c["branch"].update(candidate_source=1),
        lambda c: c["branch"].update(top_k=0),
        lambda c: c["branch"].update(top_k=True),
        lambda c: c["branch"].update(strong_signal_types=[]),
    ],
)
def test_bad_settings_are_rejected(change) -> None:
    l2 = copy.deepcopy(load_config(REPO_CONFIG)["l2"])
    change(l2)

    with pytest.raises(ConfigError):
        read_settings(l2)
