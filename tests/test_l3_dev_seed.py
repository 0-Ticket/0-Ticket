"""개발용 시드 샘플과 행 만들기(#224). DB 없이 본다."""

import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from soc.contracts import validate_contract
from soc.l3.__main__ import build_parser
from soc.l3.hunt.dev_seed import SEED_PATH, SEED_PROFILE, build_rows, load_seed

FIXTURE = Path(__file__).parent / "fixtures" / "l3_hunt" / "dev_seed.json"
DOC_NETS = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]
DAY_MS = 86_400_000
NOW_MS = 1_793_772_000_000  # 2026-11-04T06:00:00Z


def _records(seed: dict) -> list[dict]:
    return [r for s in seed["scenarios"] for r in (*s["alerts"], *s["events"])]


def _ips(value: object) -> list[str]:
    """ocsf 안의 *ip 키 값 전부."""
    if isinstance(value, dict):
        found = [v for k, v in value.items() if k == "ip" and isinstance(v, str)]
        return found + [ip for v in value.values() for ip in _ips(v)]
    if isinstance(value, list):
        return [ip for v in value for ip in _ips(v)]
    return []


def test_seed_path_points_at_the_hand_made_fixture() -> None:
    assert SEED_PATH.resolve() == FIXTURE.resolve()


def test_sample_uses_documentation_ips_and_example_com() -> None:
    seed = load_seed()
    records = _records(seed)
    ips = [e["value"] for r in records for e in r["entities"] if e["type"] == "ip"]
    ips += [ip for r in records for ip in _ips(r["ocsf"])]
    assert ips
    for ip in ips:
        assert any(ipaddress.ip_address(ip) in net for net in DOC_NETS), ip
    urls = [e["value"] for r in records for e in r["entities"] if e["type"] == "url"]
    assert urls
    for url in urls:
        host = urlsplit(url).hostname or ""
        assert host == "example.com" or host.endswith(".example.com"), url


def test_sample_has_threat_and_no_threat_scenarios_inside_lookback() -> None:
    seed = load_seed()
    assert [s["name"] for s in seed["scenarios"]] == ["threat", "no_threat"]
    threat, no_threat = seed["scenarios"]
    assert threat["alerts"] and threat["events"]  # 근거가 있다
    assert no_threat["alerts"] == []  # 가설에 맞는 Alert가 없다
    # 검증 run은 lookback_days(기본 7일) 안만 조회한다
    for record in _records(seed):
        assert 0 < record["ago_ms"] < 7 * DAY_MS


def test_build_rows_are_contract_valid_and_shifted_to_now() -> None:
    seed = load_seed()
    rows = build_rows(seed, NOW_MS)

    assert len(rows.hunts) == 2
    assert [h["details"]["scenario"] for h in rows.hunts] == ["threat", "no_threat"]
    for hunt in rows.hunts:
        validate_contract("hunt", hunt)
        assert hunt["status"] == "pending" and hunt["attempts"] == 0
        assert hunt["details"]["dev_seed"] is True
        assert hunt["created_at"] == hunt["updated_at"] == NOW_MS
    assert len({h["hunt_run_id"] for h in rows.hunts}) == 1

    expected = _records(seed)
    made = [*rows.alerts, *rows.events]
    assert len(made) == len(expected)
    assert len(rows.raw_records) == len(made)
    for raw in rows.raw_records:
        validate_contract("raw_record", raw)
        assert raw["siem_profile"] == SEED_PROFILE
    for alert in rows.alerts:
        validate_contract("alert", alert)
    for event in rows.events:
        validate_contract("event", event)
        assert event["ocsf_class"] == event["ocsf"]["class_uid"]
    # 시각은 지금 - ago_ms. 에이전트 도구가 보여 주는 Alert·Event에는 시드 표시를 넣지 않는다
    assert sorted(r["time"] for r in made) == sorted(NOW_MS - r["ago_ms"] for r in expected)
    for record in made:
        assert record["details"] == {}
    raw_by_id = {r["id"]: r for r in rows.raw_records}
    for record in made:
        assert raw_by_id[record["raw_id"]]["fetched_at"] == record["time"]


def test_build_rows_makes_new_ids_each_time() -> None:
    seed = load_seed()
    first = build_rows(seed, NOW_MS)
    second = build_rows(seed, NOW_MS)
    assert {h["id"] for h in first.hunts}.isdisjoint(h["id"] for h in second.hunts)
    assert {a["id"] for a in first.alerts}.isdisjoint(a["id"] for a in second.alerts)


def test_build_rows_rejects_bad_ago_ms(tmp_path: Path) -> None:
    broken = json.loads(FIXTURE.read_text(encoding="utf-8"))
    broken["scenarios"][0]["alerts"][0]["ago_ms"] = -1
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(ValueError):
        build_rows(load_seed(path), NOW_MS)


def test_dev_seed_command_says_it_is_for_dev_db_only(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["dev-seed", "--help"])
    help_text = capsys.readouterr().out
    assert "개발 DB 전용" in help_text
    assert "--remove" in help_text
    assert parser.parse_args(["dev-seed", "--remove"]).remove is True
    assert parser.parse_args(["dev-seed"]).remove is False
