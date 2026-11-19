"""alerts 파생 컬럼과 observables·evidences 규칙(#338, D-065). DB 없이 샘플 전체로 일치를 본다."""

import json
from pathlib import Path
from typing import Any

import pytest

from soc.contracts import validate_contract
from soc.contracts.alert import contract_data
from soc.ids import new_id
from soc.normalize.mapping import (
    RawRow,
    alert_row,
    derive_columns,
    finding_ocsf,
    normalize,
    with_derived_columns,
)
from soc.normalize.ocsf_schema import validate_ocsf

ROOT = Path(__file__).parent.parent / "fixtures" / "normalize"
CASES = json.loads((ROOT / "alert_skeleton.json").read_text(encoding="utf-8"))
CLASS_ATTRIBUTES = {
    uid: set(
        json.loads((Path("src/soc/normalize/ocsf/classes") / f"{uid}.json").read_text())[
            "attributes"
        ]
    )
    for uid in (0, 2004)
}
EVIDENCE_KEYS = {
    ("ip", "src"): lambda v: {"src_endpoint": {"ip": v}},
    ("ip", "dst"): lambda v: {"dst_endpoint": {"ip": v}},
    ("user", "actor"): lambda v: {"actor": {"user": {"name": v}}},
    ("domain", "dst"): lambda v: {"dst_endpoint": {"domain": v}},
    ("url", "dst"): lambda v: {"url": {"url_string": v}},
}
OBSERVABLE_TYPES = {
    "ip": 2,
    "host": 1,
    "domain": 1,
    "user": 4,
    "url": 6,
    "file_hash": 8,
    "process": 9,
}


def results() -> list[tuple[str, Any]]:
    out = []
    for case in CASES:
        raw = RawRow(
            id=new_id("raw"),
            kind="alert",
            original=case["original"],
            fetched_at=1_793_000_000_000 if "fetched_at" in case else None,
        )
        try:
            out.append((case["case"], normalize(raw)))
        except Exception:  # fetched_at 없는 폴백 실패 샘플은 일치 검사 대상이 아니다
            continue
    return out


RESULTS = results()


def expected_evidences(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """테스트 쪽 독립 구현: 엔티티 하나당 요소 하나, 같은 (속성, 값)은 한 번."""
    found: list[dict[str, Any]] = []
    for entity in entities:
        make = EVIDENCE_KEYS.get((entity["type"], entity["role"]))
        if make is not None and (item := make(entity["value"])) not in found:
            found.append(item)
    return found


def test_samples_cover_every_source_and_fallback() -> None:
    assert {r.source for _, r in RESULTS} >= {"suricata", "modsecurity", "guardduty", "unknown"}
    assert any(r.outcome == "fallback" for _, r in RESULTS)


@pytest.mark.parametrize(("name", "result"), RESULTS, ids=[n for n, _ in RESULTS])
def test_columns_match_the_ocsf_document(name: str, result: Any) -> None:
    row, ocsf = result.row, result.row["ocsf"]

    assert row["time"] == ocsf.get("start_time", ocsf["time"])
    assert row["title"] == (ocsf.get("finding_info", {}).get("title") or ocsf["message"])
    assert row["rule_id"] == ocsf.get("finding_info", {}).get("analytic", {}).get("uid")
    severity = ocsf["severity_id"]
    assert row["severity"] == (severity if 0 <= severity <= 6 else 0)
    assert derive_columns(ocsf) == {k: row[k] for k in ("time", "severity", "title", "rule_id")}


@pytest.mark.parametrize(("name", "result"), RESULTS, ids=[n for n, _ in RESULTS])
def test_observables_and_evidences_come_from_the_entities(name: str, result: Any) -> None:
    ocsf = result.row["ocsf"]
    entities = result.row["entities"]
    seen: dict[tuple[int, str], dict[str, Any]] = {}
    for e in entities:
        key = (OBSERVABLE_TYPES[e["type"]], e["value"])
        seen.setdefault(key, {"type_id": key[0], "value": key[1]})

    assert ocsf.get("observables") == (list(seen.values()) or None) or (
        not seen and "observables" not in ocsf
    )
    assert ocsf.get("evidences", []) == expected_evidences(entities)


@pytest.mark.parametrize(("name", "result"), RESULTS, ids=[n for n, _ in RESULTS])
def test_details_has_no_key_named_like_an_ocsf_attribute(name: str, result: Any) -> None:
    uid = result.row["ocsf"]["class_uid"]

    assert not set(result.row["details"]) & CLASS_ATTRIBUTES[uid]


def test_severity_id_99_is_folded_to_zero() -> None:
    assert derive_columns({"severity_id": 99, "time": 5, "message": "m"})["severity"] == 0
    assert derive_columns({"severity_id": 4, "time": 5, "message": "m"})["severity"] == 4


def test_derive_uses_the_fallbacks_when_finding_fields_are_missing() -> None:
    assert derive_columns({"severity_id": 0, "time": 5, "message": "m"}) == {
        "time": 5,
        "severity": 0,
        "title": "m",
        "rule_id": None,
    }
    full = {
        "severity_id": 2,
        "time": 5,
        "start_time": 7,
        "message": "m",
        "finding_info": {"title": "t", "analytic": {"uid": "r"}},
    }
    assert derive_columns(full) == {"time": 7, "severity": 2, "title": "t", "rule_id": "r"}


def test_evidences_follow_the_role_table_and_skip_target_and_null_roles() -> None:
    entities = [
        {"type": "ip", "value": "192.0.2.1", "role": "src"},
        {"type": "ip", "value": "192.0.2.1", "role": "src"},
        {"type": "ip", "value": "192.0.2.2", "role": "dst"},
        {"type": "user", "value": "alice", "role": "actor"},
        {"type": "domain", "value": "www.example.com", "role": "dst"},
        {"type": "url", "value": "/x", "role": "dst"},
        {"type": "host", "value": "web-01", "role": "target"},
        {"type": "process", "value": "a.exe", "role": None},
        {"type": "file_hash", "value": "abc", "role": "actor"},
    ]

    ocsf = finding_ocsf({"finding_info": {"uid": "u", "title": "t"}}, 10, entities)

    assert ocsf["evidences"] == [
        {"src_endpoint": {"ip": "192.0.2.1"}},
        {"dst_endpoint": {"ip": "192.0.2.2"}},
        {"actor": {"user": {"name": "alice"}}},
        {"dst_endpoint": {"domain": "www.example.com"}},
        {"url": {"url_string": "/x"}},
    ]
    assert len(ocsf["observables"]) == 8  # host·domain 둘 다 type_id 1이지만 값이 달라 모두 남는다


def test_alert_row_derives_the_columns_from_the_document() -> None:
    ocsf = finding_ocsf(
        {
            "severity_id": 3,
            "finding_info": {"uid": "u", "title": "T", "analytic": {"uid": "R", "type_id": 1}},
        },
        1234,
        [],
    )

    row = alert_row("alt_1", "raw_1", ocsf, [])

    assert (row["time"], row["severity"], row["title"], row["rule_id"]) == (1234, 3, "T", "R")
    assert row["assets"] == [] and row["triage"] is None and row["details"] == {}


def seed_alert_rows() -> list[tuple[str, dict[str, Any]]]:
    """시드 4종이 만드는 알럿 행. 고정 시각 픽스처는 ocsf만 가지고 있어 파생 컬럼을 채운다."""
    from soc.agent import dev_l1
    from soc.l3.hunt import dev_seed as l3_seed

    fixtures = Path("tests/fixtures")
    rows: list[tuple[str, dict[str, Any]]] = []
    for name, seed_path, builder in (
        ("l1_e2e", dev_l1.SEED_PATH, dev_l1.build_rows),
        ("l3_dev", l3_seed.SEED_PATH, l3_seed.build_rows),
    ):
        built = builder(json.loads(seed_path.read_text(encoding="utf-8")), 1_800_000_000_000)
        rows += [(name, row) for row in built.alerts]
    for name in ("api/ui_seed.json", "l3_hunt/seed.json"):
        for row in json.loads((fixtures / name).read_text(encoding="utf-8"))["alerts"]:
            rows.append((name, with_derived_columns(row)))
    return rows


SEED_ROWS = seed_alert_rows()


@pytest.mark.parametrize(
    ("name", "row"), SEED_ROWS, ids=[f"{n}-{i}" for i, (n, _) in enumerate(SEED_ROWS)]
)
def test_seed_alerts_are_valid_ocsf_with_columns_from_the_document(
    name: str, row: dict[str, Any]
) -> None:
    validate_ocsf(row["ocsf"])
    validate_contract("alert", contract_data("alert", row))

    assert row["time"] == row["ocsf"]["start_time"]
    assert row["ocsf"].get("evidences", []) == expected_evidences(row["entities"])
    assert not set(row["details"]) & CLASS_ATTRIBUTES[2004]


def test_seed_time_follows_now_minus_ago_ms() -> None:
    from soc.agent import dev_l1

    seed = json.loads(dev_l1.SEED_PATH.read_text(encoding="utf-8"))
    now = 1_800_000_000_000
    built = dev_l1.build_rows(seed, now)

    expected = sorted(now - s["alert"]["ago_ms"] for s in seed["scenarios"])
    assert sorted(r["time"] for r in built.alerts) == expected
    assert all(r["ocsf"]["time"] == r["time"] for r in built.alerts)
