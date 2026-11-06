"""L3 가설 헌팅의 DB 없는 규칙(#223): 설정, 결과 낮추기, 엔티티 합치기, 작업 프롬프트."""

import hashlib
from pathlib import Path
from typing import Any

import pytest

from soc.agent.types import contains_forbidden
from soc.l3.config import load_config
from soc.l3.hunt.prompts import PROMPT_DIR, load_prompt
from soc.l3.hunt.settings import ConfigError, read_hunt_settings
from soc.l3.hunt.verify import decide, merge_entities

ALT = "alt_01a19f93-1150-7000-8000-000000000001"
EVT = "evt_01a19f93-1150-7000-8000-000000000001"
AGL = "agl_01a19f93-1150-7000-8000-000000000001"


def l3(**hunt: Any) -> dict[str, Any]:
    base = {
        "collect_before": True,
        "news_window_days": 3,
        "news_limit": 5,
        "case_limit": 3,
        "max_hypotheses": 1,
        "lookback_days": 7,
        "confirm_threshold": 0.7,
        "max_attempts": 2,
    }
    return {"hunt": {**base, **hunt}, "intel": {"attack": {"version": "20.0"}}}


def test_default_config_has_hunt_settings(default_config_dir: Path) -> None:
    defaults = load_config(default_config_dir)["l3"]
    settings = read_hunt_settings(defaults)

    assert settings.collect_before is True
    assert (settings.news_window_days, settings.news_limit, settings.case_limit) == (3, 5, 3)
    assert settings.max_hypotheses == 1
    assert settings.lookback_days == 7
    assert settings.confirm_threshold == 0.7
    assert settings.max_attempts == 2
    assert settings.attack_version == defaults["intel"]["attack"]["version"]
    # 생성 워커만 읽는 값(#245). HuntSettings에는 없다
    assert defaults["hunt"]["generate_interval_seconds"] == 86_400


@pytest.mark.parametrize(
    "broken",
    [
        {"collect_before": "yes"},
        {"news_window_days": 0},
        {"news_limit": 0},
        {"news_limit": 1.5},
        {"case_limit": -1},
        {"max_hypotheses": 0},
        {"lookback_days": -1},
        {"confirm_threshold": 1.5},
        {"confirm_threshold": True},
        {"max_attempts": 0},
    ],
    ids=lambda broken: next(iter(broken)) + "=" + repr(next(iter(broken.values()))),
)
def test_broken_hunt_settings_are_rejected(broken: dict[str, Any]) -> None:
    with pytest.raises(ConfigError):
        read_hunt_settings(l3(**broken))


def test_missing_hunt_table_or_attack_version_is_rejected() -> None:
    with pytest.raises(ConfigError):
        read_hunt_settings({"intel": {"attack": {"version": "20.0"}}})
    with pytest.raises(ConfigError):
        read_hunt_settings({"hunt": l3()["hunt"], "intel": {}})


def test_case_limit_zero_is_allowed() -> None:
    assert read_hunt_settings(l3(case_limit=0)).case_limit == 0


def verification(result: str, confidence: float, evidence: list[str]) -> dict[str, Any]:
    return {
        "result": result,
        "confidence": confidence,
        "reason": "이유",
        "evidence_ids": evidence,
        "entities": [],
    }


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (verification("confirmed", 0.9, [EVT, AGL]), ("confirmed", [])),
        (verification("confirmed", 0.7, [ALT]), ("confirmed", [])),
        (verification("confirmed", 0.69, [ALT]), ("inconclusive", ["threshold"])),
        (verification("confirmed", 0.9, [AGL]), ("inconclusive", ["no_record_evidence"])),
        (verification("confirmed", 0.1, []), ("inconclusive", ["threshold", "no_record_evidence"])),
        (verification("rejected", 0.8, [AGL]), ("rejected", [])),
        (verification("rejected", 0.8, []), ("inconclusive", ["no_evidence"])),
        (verification("inconclusive", 0.2, []), ("inconclusive", [])),
    ],
    ids=[
        "confirmed",
        "confirmed_at_threshold",
        "confirmed_below_threshold",
        "confirmed_tool_log_only",
        "confirmed_both_rules",
        "rejected_tool_log",
        "rejected_without_evidence",
        "inconclusive",
    ],
)
def test_decide_downgrades_results_without_enough_ground(
    output: dict[str, Any], expected: tuple[str, list[str]]
) -> None:
    assert decide(output, threshold=0.7) == expected


IP = {"type": "ip", "value": "203.0.113.10", "role": "src"}
HOST = {"type": "host", "value": "web-01", "role": "dst"}
URL = {"type": "url", "value": "https://shop.example.com/upload.php", "role": "target"}


def test_merge_entities_keeps_records_first_and_separates_model_only() -> None:
    records = [IP, HOST, IP, URL]
    model = [{**IP}, {"type": "ip", "value": "203.0.113.10", "role": "dst"}, {**HOST, "role": None}]

    merged, model_only = merge_entities(records, model)

    assert merged == [
        IP,
        HOST,
        URL,
        {"type": "ip", "value": "203.0.113.10", "role": "dst"},
        {**HOST, "role": None},
    ]
    assert model_only == [
        {"type": "ip", "value": "203.0.113.10", "role": "dst"},
        {**HOST, "role": None},
    ]


def test_merge_entities_dedupes_model_entities_too() -> None:
    merged, model_only = merge_entities([], [IP, {**IP}])

    assert merged == [IP]
    assert model_only == [IP]


@pytest.mark.parametrize("name", ["l3_hypothesize", "l3_verify"])
def test_task_prompt_is_the_file_with_content_hash_version(name: str) -> None:
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")

    prompt = load_prompt(name)

    assert prompt.text == text
    assert prompt.version == hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("name", ["l3_hypothesize", "l3_verify"])
def test_task_prompt_avoids_forbidden_phrases(name: str) -> None:
    """TaskPrompt도 만들 때 거부하지만(#210), 어떤 문구가 걸리는지 여기서 바로 보이게 한다."""
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")

    assert not contains_forbidden(text)
