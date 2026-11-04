"""new_id(): 접두사 + UUIDv7, 만든 순서대로 정렬."""

import re
import uuid

import pytest
from contract_samples import load_schema

from soc import ids
from soc.ids import PREFIXES, new_id

# 접두사 → contracts/common/types.schema.json의 정의 이름
DEFINITIONS = {
    "raw": "raw_id",
    "alt": "alert_id",
    "evt": "event_id",
    "tkt": "ticket_id",
    "inc": "incident_id",
    "cas": "case_id",
    "agl": "agent_log_id",
    "run": "run_id",
    "hnt": "hunt_id",
    "hrn": "hunt_run_id",
}


@pytest.fixture
def fixed_clock(monkeypatch: pytest.MonkeyPatch):
    """시계를 원하는 값으로 고정하고, 이전 테스트가 남긴 상태를 지운다."""

    def set_clock(*values: int) -> None:
        clock = iter(values) if len(values) > 1 else None
        monkeypatch.setattr(ids, "_now_ms", (lambda: next(clock)) if clock else lambda: values[0])

    monkeypatch.setattr(ids, "_last_ms", -1)
    monkeypatch.setattr(ids, "_counter", 0)
    return set_clock


def test_prefixes_match_contract_ids() -> None:
    assert set(PREFIXES) == set(DEFINITIONS)


@pytest.mark.parametrize("prefix", sorted(DEFINITIONS))
def test_new_id_matches_contract_pattern(prefix: str) -> None:
    pattern = load_schema("common/types.schema.json")["definitions"][DEFINITIONS[prefix]]["pattern"]

    value = new_id(prefix)

    assert re.fullmatch(pattern, value)
    parsed = uuid.UUID(value.removeprefix(f"{prefix}_"))
    assert parsed.version == 7
    assert parsed.variant == uuid.RFC_4122


@pytest.mark.parametrize("prefix", ["usr", "hun", "tkt_", "TKT", ""])
def test_unknown_prefix_is_rejected(prefix: str) -> None:
    with pytest.raises(ValueError):
        new_id(prefix)


def test_id_starts_with_creation_time(fixed_clock) -> None:
    fixed_clock(1793678578000)  # 2026-11-03T04:02:58Z = 0x01a19f931150

    assert new_id("tkt").startswith("tkt_01a19f93-1150-7")


def test_ids_in_same_millisecond_sort_in_creation_order(fixed_clock) -> None:
    fixed_clock(1793678578000)

    values = [new_id("tkt") for _ in range(1000)]

    assert values == sorted(values)
    assert len(set(values)) == len(values)


def test_order_holds_after_counter_runs_out(fixed_clock) -> None:
    fixed_clock(1793678578000)

    values = [new_id("alt") for _ in range(10000)]  # 같은 밀리초 카운터(12비트)를 넘긴다

    assert values == sorted(values)
    assert len(set(values)) == len(values)


def test_order_holds_when_clock_goes_back(fixed_clock) -> None:
    fixed_clock(1793678578000, 1793678577000, 1793678577000, 1793678579000, 1793678500000)

    values = [new_id("evt") for _ in range(5)]

    assert values == sorted(values)
