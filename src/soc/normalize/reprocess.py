"""이미 정규화된 알럿을 id를 유지한 채 다시 정규화한다(#334, D-063).

alerts와 normalize_status를 직접 읽는다(임대 경로 claim_*_batch는 쓰지 않는다). 알럿 id·raw_id·
triage와 status·result_id·result_kind는 바꾸지 않고, 정규화가 만드는 값 중 달라진 것만 UPDATE한다.
출력에는 건수와 항목 종류만 있고 원문 값은 없다.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql

from soc.asset_lookup import AssetLookupError
from soc.contracts import ContractError, to_datetime, to_epoch_ms
from soc.normalize.config import Settings
from soc.normalize.errors import NormalizeError
from soc.normalize.mapping import RawRow, normalize
from soc.normalize.run import _checked_row, _failure_code
from soc.normalize.store import _db_value
from soc.normalize.tables import load_tables

_RANK = {"fallback": 0, "partial": 1, "ok": 2}
_ALERT_COLUMNS = ("time", "severity", "title", "rule_id", "entities", "assets", "ocsf", "details")

_CANDIDATES = """
SELECT s.raw_id FROM normalize_status s JOIN alerts a ON a.id = s.result_id
WHERE s.result_kind = 'alert' AND s.status = 'succeeded'
  AND (%s OR %s::text IS NOT NULL OR s.outcome IS NULL)
  AND (%s::timestamptz IS NULL OR a.time >= %s)
ORDER BY a.time, a.id
LIMIT %s
"""

_CURRENT = """
SELECT a.id, a.time, a.severity, a.title, a.rule_id, a.entities, a.assets, a.ocsf, a.details,
       s.outcome, s.source, s.missing_fields, s.error_code
FROM normalize_status s JOIN alerts a ON a.id = s.result_id
WHERE s.raw_id = %s AND s.result_kind = 'alert' AND s.status = 'succeeded'
"""


@dataclass
class ReprocessResult:
    """재처리 한 번의 결과.

    Attributes:
        dry_run: 쓰지 않고 센 결과인지.
        read: 읽어 다시 정규화한 행 수.
        changed: 달라져서 갱신한(dry_run이면 갱신할) 행 수.
        unchanged: 새 결과가 기존과 같은 행 수.
        other_source: `--source`와 새 결과의 소스가 달라 건드리지 않은 행 수.
        skipped: 건너뛴 사유별 건수. fallback, worse, 또는 정규화 실패 코드.
        errors: DB 오류로 그 행만 되돌린 건수.
        duplicates: 같은 raw_id에서 result_id가 아니라서 건드리지 않은 알럿 수.
        by_source: 새 결과의 소스별 changed·unchanged·skipped 건수.
        columns: 바뀌는 컬럼 이름별 행 수.
        entity_changes: 엔티티 type·role 추가(`+ip/dst`)·제거(`-ip/dst`) 건수.
    """

    dry_run: bool = False
    read: int = 0
    changed: int = 0
    unchanged: int = 0
    other_source: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    errors: int = 0
    duplicates: int = 0
    by_source: dict[str, dict[str, int]] = field(default_factory=dict)
    columns: dict[str, int] = field(default_factory=dict)
    entity_changes: dict[str, int] = field(default_factory=dict)


def reprocess(
    settings: Settings,
    conn: psycopg.Connection,
    *,
    source: str | None = None,
    since: datetime | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    all_rows: bool = False,
) -> ReprocessResult:
    """대상 알럿을 새 로직으로 다시 정규화해 달라진 행만 갱신한다.

    Args:
        settings: 정규화 설정.
        conn: DB 연결(autocommit).
        source: 새 결과의 소스가 이것인 알럿만. 주면 outcome과 관계없이 모든 알럿을 읽는다.
        since: alerts.time이 이 시각 이후인 알럿만.
        limit: 읽을(정규화할) 최대 행 수. alerts.time, id 오름차순.
        dry_run: 어떤 테이블에도 쓰지 않고 잠그지도 않는다.
        all_rows: outcome과 관계없이 기존 알럿 전체를 읽는다. 폴백·outcome 하락은 그대로 건너뛴다.

    Raises:
        MappingTableError: 매핑표가 틀렸다. 읽기 전에 난다.
    """
    load_tables()
    result = ReprocessResult(dry_run=dry_run)
    rows = conn.execute(_CANDIDATES, (all_rows, source, since, since, limit)).fetchall()
    for (raw_id,) in rows:
        result.read += 1
        try:
            with conn.transaction():
                _one(settings, conn, raw_id, source, dry_run, result)
        except (NormalizeError, AssetLookupError, ContractError) as error:
            _count_skip(result, None, _failure_code(error))
        except psycopg.Error:
            result.errors += 1
    return result


def _one(
    settings: Settings,
    conn: psycopg.Connection,
    raw_id: str,
    source: str | None,
    dry_run: bool,
    result: ReprocessResult,
) -> None:
    """원본 한 건을 다시 정규화해 기존 행과 비교하고, 달라졌으면 갱신한다. 열린 트랜잭션 안이다."""
    lock = sql.SQL("" if dry_run else " FOR UPDATE OF a, s")
    current = conn.execute(sql.SQL(_CURRENT) + lock, (raw_id,)).fetchone()
    raw = _read_raw(conn, raw_id)
    if current is None or raw is None:
        return  # 읽은 뒤 다른 곳에서 바뀌었다. 다음 실행이 다시 본다
    (alert_id, *old_alert, old_outcome, old_source, old_missing, old_code) = current
    old = dict(zip(_ALERT_COLUMNS, old_alert, strict=True))
    mapped = normalize(raw)
    new_source = mapped.source or "unknown"
    if source is not None and new_source != source:
        result.other_source += 1
        return
    if mapped.outcome == "fallback":
        _count_skip(result, new_source, "fallback")
        return
    if old_outcome is not None and _RANK[mapped.outcome or "ok"] < _RANK[old_outcome]:
        _count_skip(result, new_source, "worse")
        return
    row = _checked_row(settings, conn, mapped, (old["entities"], old["assets"]))
    changed_alert = {
        column: row[column]
        for column in _ALERT_COLUMNS
        if _differs(column, old[column], row[column])
    }
    new_status = {
        "outcome": mapped.outcome,
        "source": mapped.source,
        "missing_fields": list(mapped.missing_fields),
        "error_code": mapped.error_code,
    }
    old_status = {
        "outcome": old_outcome,
        "source": old_source,
        "missing_fields": list(old_missing),
        "error_code": old_code,
    }
    changed_status = {c: v for c, v in new_status.items() if v != old_status[c]}
    result.duplicates += conn.execute(
        "SELECT count(*) FROM alerts WHERE raw_id = %s AND id <> %s", (raw_id, alert_id)
    ).fetchone()[0]
    counts = result.by_source.setdefault(new_source, {"changed": 0, "unchanged": 0, "skipped": 0})
    if not changed_alert and not changed_status:
        result.unchanged += 1
        counts["unchanged"] += 1
        return
    result.changed += 1
    counts["changed"] += 1
    for column in (*changed_alert, *changed_status):
        result.columns[column] = result.columns.get(column, 0) + 1
    if "entities" in changed_alert:
        _count_entities(result, old["entities"], row["entities"])
    if not dry_run:
        _update(conn, raw_id, alert_id, changed_alert, changed_status)


def _read_raw(conn: psycopg.Connection, raw_id: str) -> RawRow | None:
    """원본 한 건을 읽는다. 저장된 JSON 글자를 그대로 되살린다(D-049)."""
    row = conn.execute(
        "SELECT id, kind, original_text, fetched_at FROM raw_records WHERE id = %s", (raw_id,)
    ).fetchone()
    if row is None:
        return None
    return RawRow(
        id=row[0], kind=row[1], original=json.loads(row[2]), fetched_at=to_epoch_ms(row[3])
    )


def _differs(column: str, old: Any, new: Any) -> bool:
    """저장된 값과 새 값이 다른지. 시각은 DB 값(datetime)과 epoch 밀리초를 맞춰 비교한다."""
    return old != (to_datetime(new) if column == "time" else new)


def _count_skip(result: ReprocessResult, source: str | None, reason: str) -> None:
    result.skipped[reason] = result.skipped.get(reason, 0) + 1
    if source is not None:
        counts = result.by_source.setdefault(source, {"changed": 0, "unchanged": 0, "skipped": 0})
        counts["skipped"] += 1


def _count_entities(result: ReprocessResult, old: list[Any], new: list[Any]) -> None:
    """엔티티 type·role이 더해지고 빠진 건수를 센다. 값은 세지 않는다."""
    before = Counter((e["type"], e.get("role"), e["value"]) for e in old)
    after = Counter((e["type"], e.get("role"), e["value"]) for e in new)
    for sign, entries in (("+", after - before), ("-", before - after)):
        for (kind, role, _value), number in entries.items():
            key = f"{sign}{kind}/{role}"
            result.entity_changes[key] = result.entity_changes.get(key, 0) + number


def _update(
    conn: psycopg.Connection,
    raw_id: str,
    alert_id: str,
    alert: dict[str, Any],
    status: dict[str, Any],
) -> None:
    """달라진 컬럼만 UPDATE한다. 열린 트랜잭션 안이고 행은 이미 잠겨 있다."""
    for table, changes, key, value in (
        ("alerts", alert, "id", alert_id),
        ("normalize_status", status, "raw_id", raw_id),
    ):
        if not changes:
            continue
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = {}").format(sql.Identifier(column), sql.Placeholder())
            for column in changes
        )
        query = sql.SQL("UPDATE {} SET {} WHERE {} = {}").format(
            sql.Identifier(table), assignments, sql.Identifier(key), sql.Placeholder()
        )
        conn.execute(query, [*(_db_value(c, v) for c, v in changes.items()), value])


def exit_code(result: ReprocessResult) -> int:
    """DB 오류가 있으면 1, 없으면 0. 건너뜀은 정상 동작이다."""
    return 1 if result.errors else 0


def format_result(result: ReprocessResult) -> str:
    """결과를 줄로 만든다. 건수와 항목 종류만 있다."""
    verb = "would_update" if result.dry_run else "updated"
    prefix = "dry-run " if result.dry_run else ""
    skipped = " ".join(f"{k}={v}" for k, v in sorted(result.skipped.items()))
    lines = [
        f"{prefix}read={result.read} {verb}={result.changed} unchanged={result.unchanged}"
        f" skipped={sum(result.skipped.values())} other_source={result.other_source}"
        f" errors={result.errors} duplicate_alerts={result.duplicates}"
    ]
    if skipped:
        lines.append(f"skipped by reason: {skipped}")
    for name, counts in sorted(result.by_source.items()):
        lines.append(
            f"{name} {verb}={counts['changed']} unchanged={counts['unchanged']}"
            f" skipped={counts['skipped']}"
        )
    if result.columns:
        lines.append("columns: " + " ".join(f"{k}={v}" for k, v in sorted(result.columns.items())))
    if result.entity_changes:
        lines.append(
            "entities: " + " ".join(f"{k}={v}" for k, v in sorted(result.entity_changes.items()))
        )
    return "\n".join(lines)
