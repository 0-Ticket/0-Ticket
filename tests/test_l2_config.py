"""L2 설정 로더와 분류 설정 검증."""

import copy
from pathlib import Path

import pytest

from soc.l2.config import ConfigError, load_config, read_settings

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"


def test_default_config_reads_into_branch_settings() -> None:
    config = load_config(REPO_CONFIG)
    settings = read_settings(config["l2"])

    assert set(config) == {"l2"}
    assert settings.candidate_window_ms == 86_400_000
    assert settings.max_candidates == 5
    assert settings.strong_signal_types == frozenset(
        {"file_hash", "process", "url", "domain", "user"}
    )
    assert settings.weak_signal_types == frozenset({"ip", "host"})
    assert settings.shared_entity_values == ()


def test_local_overrides_default_and_only_l2_is_returned(tmp_path: Path) -> None:
    (tmp_path / "default.toml").write_text(
        "[l2.branch]\n"
        "candidate_window_ms = 1000\n"
        "max_candidates = 5\n"
        'strong_signal_types = ["file_hash"]\n'
        'weak_signal_types = ["ip", "host", "user", "domain", "url", "process"]\n'
        "shared_entity_values = []\n"
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
                "strong_signal_types": ["file_hash"],
                "weak_signal_types": ["ip", "host", "user", "domain", "url", "process"],
                "shared_entity_values": [],
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
        lambda c: c["branch"].update(strong_signal_types=["file_hash", "email"]),
        lambda c: c["branch"].update(weak_signal_types=["ip", "file_hash"]),
        lambda c: c["branch"].update(weak_signal_types=["ip"]),
        lambda c: c["branch"].update(shared_entity_values=[""]),
        lambda c: c["branch"].update(shared_frequency_threshold=10),
    ],
)
def test_bad_settings_are_rejected(change) -> None:
    l2 = copy.deepcopy(load_config(REPO_CONFIG)["l2"])
    change(l2)

    with pytest.raises(ConfigError):
        read_settings(l2)
