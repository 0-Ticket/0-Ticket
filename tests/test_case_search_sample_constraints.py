"""Case 검색 샘플(tests/fixtures/case_search/cases.json)이 DB 제약을 지키는지 DB 없이 본다(#392).

DB 테스트(test_tools_case_search_db.py)는 샘플을 실제 표에 넣는데, 제약을 어기면 CI에서야 알게 된다
(Ticket 하나에 Alert 둘로 0104의 tickets_auto_scenario_l1_single_alert_check를 어긴 적이 있다).
여기서는 마이그레이션 파일을 읽어 제약이 아래 검사와 같은지 대조하고(값 목록은 SQL에서 읽는다),
샘플의 모든 행을 같은 검사로 본다. 표 종류가 늘거나 새 제약이 생기면 아래 목록이 어긋나 실패한다.
"""

import copy
import re
from collections.abc import Callable
from typing import Any

import pytest
from case_search_helpers import SAMPLE

from soc.db.migrate import MIGRATIONS_DIR

TABLES = (
    "raw_records",
    "alerts",
    "hunts",
    "tickets",
    "incidents",
    "incident_artifacts",
    "incident_proposals",
    "cases",
)
WHITESPACE = "\t\n\x0b\x0c\r  　"  # 0109·0202의 title CHECK가 말하는 공백

# 마이그레이션이 이 표들에 거는 제약을 이름이나 칸으로 센 것. 새 마이그레이션이 제약을 더하거나
# 바꾸면 이 목록과 달라져 테스트가 실패한다. 그때는 샘플이 지키는지 보고 아래 검사에 더한다.
COVERED_NAMED = {
    "add_constraint": {
        "tickets_origin_hunt_id_check",  # 0002
        "tickets_auto_scenario_l1_single_alert_check",  # 0104
        "tickets_title_check",  # 0109
        "alerts_ocsf_class_check",  # 0303
        "incidents_status_check",  # 0201(0001의 칸 CHECK를 바꾼다)
        "incident_proposals_kind_check",  # 0202(0200의 칸 CHECK를 바꾼다)
        "incident_proposals_artifact_id_seq_key",  # 0202(0200의 UNIQUE를 바꾼다)
        "incident_proposals_title_check",  # 0202
    },
    "unique_index": {"tickets_auto_scenario_l1_alert_uidx"},  # 0104
    "add_column": {
        ("tickets", "hunt_id"),  # 0002: UNIQUE REFERENCES hunts
        ("incident_proposals", "priority"),  # 0202: CHECK
        ("incident_proposals", "title"),  # 0202: NOT NULL·incident_proposals_title_check
        ("raw_records", "original_text"),  # 0106: CHECK (left(original_text, 1) = '{')
    },
}


def _strip_comments(text: str) -> str:
    return re.sub(r"--[^\n]*", "", text)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _load() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """(표 -> CREATE TABLE·ALTER TABLE 글자, 인덱스 이름 -> 정의, 모든 SQL)."""
    tables: dict[str, list[str]] = {name: [] for name in TABLES}
    indexes: dict[str, str] = {}
    every = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        text = _strip_comments(path.read_text(encoding="utf-8"))
        every.append(text)
        for match in re.finditer(r"CREATE TABLE (\w+) \((.*?)\n\);", text, re.S):
            if match.group(1) in tables:
                tables[match.group(1)].append(match.group(2))
        for match in re.finditer(r"ALTER TABLE (\w+)\s(.*?);", text, re.S):
            if match.group(1) in tables:
                tables[match.group(1)].append(match.group(2))
        for match in re.finditer(r"CREATE UNIQUE INDEX (\w+)\s+ON (.*?);", text, re.S):
            indexes[match.group(1)] = _normalize(match.group(2))
    joined = {name: _normalize(" ".join(parts)) for name, parts in tables.items()}
    return joined, indexes, {"all": "\n".join(every)}


TABLE_SQL, INDEX_SQL, ALL_SQL = _load()


def values(table: str, anchor: str) -> list[str]:
    """`<anchor> IN ('a', 'b')`의 값 목록. 같은 표에 여러 번 나오면 마지막(바뀐 뒤) 것이다."""
    found = re.findall(re.escape(anchor) + r"\)? IN \(([^)]*)\)", TABLE_SQL[table])
    assert found, f"{table}의 마이그레이션에서 `{anchor} IN (...)`를 찾지 못했다"
    return re.findall(r"'([^']*)'", found[-1])


def declared(table: str, snippet: str) -> bool:
    return _normalize(snippet) in TABLE_SQL[table]


def _in(row: dict[str, Any], key: str, allowed: list[str]) -> list[str]:
    return [] if row[key] in allowed else [f"{key}={row[key]!r}는 {allowed}에 없다"]


def _range(row: dict[str, Any], key: str, low: int, high: int | None = None) -> list[str]:
    value = row[key]
    if value is None or (value >= low and (high is None or value <= high)):
        return []
    return [f"{key}={value!r}가 범위({low}~{high}) 밖이다"]


def _kind(row: dict[str, Any], key: str, kind: type) -> list[str]:
    return [] if isinstance(row[key], kind) else [f"{key}가 {kind.__name__}이 아니다"]


def _no_null_items(row: dict[str, Any], key: str) -> list[str]:
    return [f"{key}에 null이 있다"] if any(x is None for x in row[key]) else []


def _has_visible_char(text: str) -> bool:
    return any(ch not in WHITESPACE for ch in text)


def _unique(
    rows: list[dict[str, Any]], key: Callable[[dict[str, Any]], Any], what: str
) -> list[str]:
    seen: set[Any] = set()
    problems = []
    for row in rows:
        k = key(row)
        if k is None:
            continue  # UNIQUE는 NULL끼리 겹쳐도 막지 않는다
        if k in seen:
            problems.append(f"{what}이 겹친다: {k!r}")
        seen.add(k)
    return problems


def violations(sample: dict[str, Any]) -> list[str]:
    """샘플이 어기는 제약을 `표 id: 내용`으로 모두 돌려준다. 비어 있으면 지킨 것이다."""
    out: list[str] = []

    def add(table: str, row: dict[str, Any], problems: list[str]) -> None:
        out.extend(f"{table} {row.get('id', row.get('artifact_id'))}: {p}" for p in problems)

    ids = {t: {r["id"] for r in sample[t]} for t in TABLES if t != "raw_records"}
    ids["raw_records"] = {r["id"] for r in sample["raw_records"]}
    for table in TABLES:
        out.extend(f"{table}: {p}" for p in _unique(sample[table], lambda r: r["id"], "id(PK)"))

    for r in sample["raw_records"]:
        add("raw_records", r, _in(r, "kind", values("raw_records", "kind")))
        if not r["original_text"].startswith("{"):  # 0106
            add("raw_records", r, ["original_text가 '{'로 시작하지 않는다"])
    out += [
        f"raw_records: {p}"
        for p in _unique(
            sample["raw_records"],
            lambda r: (r["siem_profile"], r["siem_ref"]),
            "UNIQUE(siem_profile, siem_ref)",
        )
    ]

    classes = values("alerts", "(ocsf ->> 'class_uid')")
    triage_states = values("alerts", "triage ->> 'status'")
    for r in sample["alerts"]:
        problems = _range(r, "severity", 0, 6)
        problems += _kind(r, "entities", list) + _kind(r, "assets", list)
        problems += _kind(r, "ocsf", dict) + _kind(r, "details", dict)
        if str(r["ocsf"].get("class_uid")) not in classes:  # 0303
            problems.append("ocsf.class_uid가 허용 값이 아니다")
        triage = r["triage"]
        if triage is not None and not (
            isinstance(triage, dict) and triage.get("status") in triage_states
        ):
            problems.append("triage가 객체이고 status가 목록 값이어야 한다")
        if r["raw_id"] not in ids["raw_records"]:
            problems.append("raw_id가 raw_records에 없다")
        add("alerts", r, problems)

    for r in sample["hunts"]:
        problems = _in(r, "status", values("hunts", "status"))
        problems += _range(r, "confidence", 0, 1) + _range(r, "attempts", 0)
        problems += _no_null_items(r, "attack_techniques") + _no_null_items(r, "evidence_ids")
        problems += _kind(r, "entities", list) + _kind(r, "details", dict)
        add("hunts", r, problems)

    origins = values("tickets", "origin")
    scoped = re.findall(
        r"'([^']*)'", INDEX_SQL["tickets_auto_scenario_l1_alert_uidx"].split("WHERE", 1)[1]
    )
    for r in sample["tickets"]:
        problems = _in(r, "origin", origins) + _in(r, "status", values("tickets", "status"))
        problems += _no_null_items(r, "alert_ids") + _kind(r, "entities", list)
        problems += _kind(r, "details", dict)
        if r["verdict"] is not None and not isinstance(r["verdict"], dict):
            problems.append("verdict가 null이나 객체가 아니다")
        count = len(r["alert_ids"])
        if r["origin"] != "l3" and count < 1:  # 0001
            problems.append("l3가 아닌 Ticket은 Alert가 하나 이상이어야 한다")
        if r["origin"] != "l3" and count != 1:  # 0104
            problems.append(f"l3가 아닌 Ticket은 Alert가 정확히 하나여야 한다(지금 {count}개)")
        if (r["origin"] == "l3") != (r["hunt_id"] is not None):  # 0002
            problems.append("l3 Ticket만 hunt_id를 가져야 한다")
        if r["hunt_id"] is not None and r["hunt_id"] not in ids["hunts"]:
            problems.append("hunt_id가 hunts에 없다")
        if not _has_visible_char(r["title"]):  # 0109
            problems.append("title에 공백 밖 글자가 없다")
        for alert in r["alert_ids"]:
            if alert not in ids["alerts"]:
                problems.append(f"alert {alert}가 alerts에 없다(sample 일관성)")
        add("tickets", r, problems)
    out += [
        f"tickets: {p}"
        for p in _unique(sample["tickets"], lambda r: r["hunt_id"], "hunt_id UNIQUE")
    ]
    out += [  # 0104의 부분 유일 인덱스: 같은 Alert로 auto·scenario·l1 Ticket을 둘 만들 수 없다
        f"tickets: {p}"
        for p in _unique(
            sample["tickets"],
            lambda r: r["alert_ids"][0] if r["origin"] in scoped and r["alert_ids"] else None,
            "alert_ids[1](auto·scenario·l1)",
        )
    ]

    for r in sample["incidents"]:
        problems = _in(r, "status", values("incidents", "status"))
        problems += _range(r, "severity", 0, 6) + _range(r, "assessed_severity", 0, 6)
        problems += _range(r, "analysis_round", 0) + _range(r, "review_round", 0)
        problems += _no_null_items(r, "ticket_ids") + _kind(r, "entities", list)
        problems += _kind(r, "details", dict)
        if len(r["ticket_ids"]) < 1:
            problems.append("ticket_ids가 비어 있다")
        problems += [
            f"ticket {t}가 tickets에 없다" for t in r["ticket_ids"] if t not in ids["tickets"]
        ]
        add("incidents", r, problems)

    for r in sample["incident_artifacts"]:
        problems = _in(r, "verdict", values("incident_artifacts", "verdict"))
        problems += _range(r, "analysis_round", 1) + _range(r, "assessed_severity", 0, 6)
        problems += _kind(r, "timeline", list) + _kind(r, "techniques", list)
        problems += _no_null_items(r, "evidence_ids")
        if r["summary"] == "":
            problems.append("summary가 빈 문자열이다")
        if r["incident_id"] not in ids["incidents"]:
            problems.append("incident_id가 incidents에 없다")
        add("incident_artifacts", r, problems)
    out += [
        f"incident_artifacts: {p}"
        for p in _unique(
            sample["incident_artifacts"],
            lambda r: (r["incident_id"], r["analysis_round"]),
            "UNIQUE(incident_id, analysis_round)",
        )
    ]

    priorities = values("incident_proposals", "priority")
    for r in sample["incident_proposals"]:
        problems = _in(r, "kind", values("incident_proposals", "kind")) + _range(r, "seq", 1)
        if r["priority"] is not None and r["priority"] not in priorities:
            problems.append(f"priority={r['priority']!r}는 {priorities}에 없다")
        if r["detail"] == "":
            problems.append("detail이 빈 문자열이다")
        if not _has_visible_char(r["title"]):  # 0202
            problems.append("title에 공백 밖 글자가 없다")
        if r["artifact_id"] not in ids["incident_artifacts"]:
            problems.append("artifact_id가 incident_artifacts에 없다")
        add("incident_proposals", r, problems)
    out += [
        f"incident_proposals: {p}"
        for p in _unique(
            sample["incident_proposals"],
            lambda r: (r["artifact_id"], r["seq"]),
            "UNIQUE(artifact_id, seq)",
        )
    ]

    for r in sample["cases"]:
        problems = _in(r, "status", values("cases", "status")) + _range(r, "severity", 0, 6)
        problems += _kind(r, "entities", list) + _kind(r, "details", dict)
        if r["incident_id"] not in ids["incidents"]:
            problems.append("incident_id가 incidents에 없다")
        add("cases", r, problems)
    out += [
        f"cases: {p}"
        for p in _unique(sample["cases"], lambda r: r["incident_id"], "incident_id UNIQUE")
    ]
    return out


def test_every_sample_row_keeps_the_table_constraints() -> None:
    assert violations(SAMPLE) == []


def test_a_ticket_with_two_alerts_is_caught() -> None:
    """CI에서 실제로 났던 실수(auto Ticket 하나에 Alert 둘)를 이 검사가 잡는다."""
    broken = copy.deepcopy(SAMPLE)
    ticket = next(t for t in broken["tickets"] if t["origin"] == "auto")
    ticket["alert_ids"] = [ticket["alert_ids"][0], broken["alerts"][-1]["id"]]

    assert any("정확히 하나" in v for v in violations(broken))


@pytest.mark.parametrize(
    ("table", "key", "bad", "needle"),
    [
        ("tickets", "origin", "manual", "origin"),
        ("incident_artifacts", "verdict", "maybe", "verdict"),
        ("incidents", "status", "open", "status"),
        ("incident_proposals", "kind", "detection_rule", "kind"),
        ("cases", "status", "closed", "status"),
    ],
)
def test_a_value_outside_the_sql_list_is_caught(
    table: str, key: str, bad: str, needle: str
) -> None:
    broken = copy.deepcopy(SAMPLE)
    broken[table][0][key] = bad

    assert any(needle in v for v in violations(broken))


def test_duplicates_the_tables_forbid_are_caught() -> None:
    broken = copy.deepcopy(SAMPLE)
    broken["incident_proposals"].append(dict(broken["incident_proposals"][0], id="dup"))
    broken["cases"].append(dict(broken["cases"][0], id="cas_dup"))
    broken["tickets"].append(dict(broken["tickets"][0], id="tkt_dup"))

    found = " ".join(violations(broken))
    assert "UNIQUE(artifact_id, seq)" in found
    assert "incident_id UNIQUE" in found
    assert "alert_ids[1]" in found


# 마이그레이션과 대조: 위 검사가 가정한 제약이 SQL에 그대로 있다
DECLARED = [
    ("raw_records", "kind text NOT NULL CHECK (kind IN ('alert', 'event'))"),
    ("raw_records", "UNIQUE (siem_profile, siem_ref)"),
    ("raw_records", "CHECK (left(original_text, 1) = '{')"),
    ("alerts", "severity smallint NOT NULL CHECK (severity BETWEEN 0 AND 6)"),
    ("alerts", "raw_id text NOT NULL REFERENCES raw_records (id)"),
    ("alerts", "CHECK ((ocsf ->> 'class_uid') IN ('2004', '0'))"),
    ("hunts", "confidence double precision CHECK (confidence BETWEEN 0 AND 1)"),
    ("hunts", "attempts integer NOT NULL CHECK (attempts >= 0)"),
    ("tickets", "CHECK (origin = 'l3' OR cardinality(alert_ids) >= 1)"),
    ("tickets", "CHECK (origin = 'l3' OR cardinality(alert_ids) = 1)"),
    ("tickets", "CHECK ((origin = 'l3') = (hunt_id IS NOT NULL))"),
    ("tickets", "ADD COLUMN hunt_id text UNIQUE REFERENCES hunts (id)"),
    ("tickets", "CHECK (title ~ E'[^\\\\t\\\\n\\\\u000b\\\\f\\\\r \\\\u00a0\\\\u3000]')"),
    ("incidents", "CHECK (cardinality(ticket_ids) >= 1)"),
    ("incidents", "severity smallint NOT NULL CHECK (severity BETWEEN 0 AND 6)"),
    ("incidents", "analysis_round integer NOT NULL CHECK (analysis_round >= 0)"),
    ("incidents", "review_round integer NOT NULL CHECK (review_round >= 0)"),
    ("incident_artifacts", "analysis_round integer NOT NULL CHECK (analysis_round >= 1)"),
    ("incident_artifacts", "summary text NOT NULL CHECK (summary <> '')"),
    ("incident_artifacts", "UNIQUE (incident_id, analysis_round)"),
    ("incident_artifacts", "incident_id text NOT NULL REFERENCES incidents (id)"),
    ("incident_proposals", "seq integer NOT NULL CHECK (seq >= 1)"),
    ("incident_proposals", "UNIQUE (artifact_id, seq)"),
    ("incident_proposals", "artifact_id text NOT NULL REFERENCES incident_artifacts (id)"),
    ("incident_proposals", "CHECK (priority IN ('high', 'medium', 'low'))"),
    ("cases", "incident_id text NOT NULL UNIQUE REFERENCES incidents (id)"),
    ("cases", "severity smallint NOT NULL CHECK (severity BETWEEN 0 AND 6)"),
]


@pytest.mark.parametrize(("table", "snippet"), DECLARED)
def test_the_migrations_still_declare_what_the_checks_assume(table: str, snippet: str) -> None:
    assert declared(table, snippet), f"{table}의 마이그레이션에서 `{snippet}`를 찾지 못했다"


def test_the_partial_unique_index_scopes_auto_scenario_and_l1() -> None:
    index = INDEX_SQL["tickets_auto_scenario_l1_alert_uidx"]

    assert index.startswith("tickets ((alert_ids[1]))")
    assert re.findall(r"'([^']*)'", index.split("WHERE", 1)[1]) == ["auto", "scenario", "l1"]


def test_no_new_constraint_slipped_in_without_a_check() -> None:
    """이 표들에 새 이름 있는 제약·유일 인덱스·제약 있는 칸이 생기면 여기서 알아챈다."""
    names = set(re.findall(r"ADD CONSTRAINT (\w+)", ALL_SQL["all"]))
    on_tables = {
        n
        for n in names
        if any(
            re.search(rf"ALTER TABLE {t}\s[^;]*ADD CONSTRAINT {n}\b", ALL_SQL["all"])
            for t in TABLES
        )
    }
    columns = {
        (t, c)
        for t in TABLES
        for c in re.findall(
            r"ADD COLUMN (\w+) [^,;]*?(?:CHECK|UNIQUE|REFERENCES)",
            " ".join(m for m in re.findall(rf"ALTER TABLE {t}\s([^;]*);", ALL_SQL["all"])),
        )
    }

    assert on_tables == COVERED_NAMED["add_constraint"]
    assert set(INDEX_SQL) & {"tickets_auto_scenario_l1_alert_uidx"} == COVERED_NAMED["unique_index"]
    assert {i for i, d in INDEX_SQL.items() if d.split(" ", 1)[0] in TABLES} == COVERED_NAMED[
        "unique_index"
    ]
    assert columns == COVERED_NAMED["add_column"]
